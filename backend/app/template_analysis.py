"""
Анализ шаблона: определение ТИПОВ полей для автоматического построения формы.

Проблема: docxtpl отдаёт плоский список меток. Форма не может отличить
    name    — текстовое поле
    tracks  — таблица с добавлением строк
    edo     — галочка
и сгенерирует три одинаковых <input type="text">.

Решение: тип выводится из самого шаблона, а не хранится в БД.
    {% for t in tracks %}   -> tracks это список, а t.title -> колонка таблицы
    {% if edo %}             -> edo это флаг (используется только в условии)
    {{ name }}                -> обычное текстовое поле

Так тип не может рассинхронизироваться с шаблоном: поменял разметку —
форма перестроилась сама.

Отдельно исключаются ВЫЧИСЛЯЕМЫЕ поля (contract, profanity_note и т.д.) —
их считает context_builder, оператор их не вводит.
"""
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date as _date

# Поля, которые вычисляет context_builder — в форме не показываются.
# Синхронизировано с context_builder.build_context()
#
# contract и date — вычисляемые ТОЛЬКО для комбинированного Договора
# (doc_type='contract'). Для отдельных Приложения/Акта (doc_type in
# 'appendix'/'act') они, наоборот, обычные поля ввода — см.
# computed_fields_for() ниже, которая убирает их из этого множества.
COMPUTED_FIELDS = {
    "contract",         # комбинированный Договор: из даты + инициалов ФИО
    "name_short",       # из ФИО
    "profanity_note",   # из галочек НЛ у треков
    "performer_note",   # из списка исполнителей
    "release_label",    # из release_type
    "date",             # комбинированный Договор: дублирует c_date
    "royalty_text",     # числительное прописью из royalty (числа)
    "advance_text",     # пропись суммы аванса из advance (числа)
    "smm_text",         # пропись суммы SMM из smm (числа)
    "penalty_text",     # пропись штрафа из penalty (числа)
    "count_text",       # пропись количества треков из count (числа)
    "advance_days_text",# пропись срока выплаты аванса из advance_days (числа)
}

# Приложение/Акт — отдельный файл, привязанный к уже существующему
# договору. Базы контрагентов пока нет (этап 4), поэтому номер и дату
# этого договора вводит оператор вручную — здесь их нельзя вычислить.
LINKED_DOC_TYPES = {"appendix", "act"}


def computed_fields_for(doc_type: str | None) -> set[str]:
    """
    COMPUTED_FIELDS с поправкой на doc_type шаблона.

    Для Приложения/Акта (LINKED_DOC_TYPES): contract и date, наоборот,
    становятся обычными полями ввода (убираем из вычисляемых), а c_date,
    наоборот, добавляется в вычисляемые — дата того договора парсится
    прямо из его номера (contract_date_iso в context_builder.py), вводить
    её отдельно не нужно.
    """
    if doc_type in LINKED_DOC_TYPES:
        return (COMPUTED_FIELDS - {"contract", "date"}) | {"c_date"}
    return COMPUTED_FIELDS

# Служебные переменные Jinja, не являющиеся полями
JINJA_BUILTINS = {"loop"}

# Перечисления, которые НЕЛЬЗЯ вывести из шаблона целиком.
# Шаблон содержит только `release_type != 'none'`, но реальных значений три.
# Здесь задаём полный список вариантов и человекочитаемые подписи.
KNOWN_CHOICES = {
    "release_type": [
        ("none", "Сингл"),
        ("ep", "ЕР"),
        ("album", "Альбом"),
    ],
}

# Человекочитаемые подписи и группировка.
# Ключ — имя метки, значение — (группа, подпись, подсказка).
# Метки, которых здесь нет, попадут в группу «Прочее» с именем как есть.
FIELD_META = {
    # Контрагент
    "name":       ("Контрагент", "ФИО полностью", "Иванов Иван Иванович"),
    "inn":        ("Контрагент", "ИНН", "771234567890"),
    "nickname":   ("Контрагент", "Псевдоним", "если нет — оставьте пустым"),

    # Личные данные (бывший "Паспорт" — расширен датой рождения и НПД,
    # они переехали сюда из "Контрагент" и поставлены в конец блока)
    "serial":     ("Личные данные", "Серия паспорта", "4500"),
    "number":     ("Личные данные", "Номер паспорта", "123456"),
    "pas_place":  ("Личные данные", "Кем выдан", ""),
    "pas_date":   ("Личные данные", "Дата выдачи", ""),
    "kp":         ("Личные данные", "Код подразделения", "770-001"),
    "npd":        ("Личные данные", "Дата и место постановки на учёт НПД", ""),
    "birthday":   ("Личные данные", "Дата рождения", ""),

    # Контакты
    "adress":     ("Контакты", "Адрес", ""),
    "phone":      ("Контакты", "Телефон", "+7 900 000-00-00"),
    "mail":       ("Контакты", "E-mail", ""),

    # Реквизиты
    "rs":         ("Банковские реквизиты", "Расчётный счёт", ""),
    "bank":       ("Банковские реквизиты", "Банк", ""),
    "ks":         ("Банковские реквизиты", "Корр. счёт", ""),
    "bik":        ("Банковские реквизиты", "БИК", ""),

    # Документ
    "c_date":     ("Документ", "Дата",
                   "единая дата для договора и документа — номер договора соберётся из неё автоматически"),
    "appendix_no":("Документ", "Номер приложения", "1"),
    "act_no":     ("Документ", "Номер акта", "1"),
    "edo":        ("Документ", "Подписание через ЭДО",
                   "в нижнем колонтитуле останется только номер страницы"),
    "royalty":    ("Документ", "Роялти, %", "целое число 0-100, напр. 50"),
    "term_end":   ("Документ", "Срок действия",
                   "предзаполняется как дата документа +5 лет до конца квартала — можно поправить вручную"),
    "advance":    ("Документ", "Сумма аванса, ₽",
                   "полная сумма числом, напр. 150000 — пропись подставится сама"),
    "advance_days": ("Документ", "Срок выплаты аванса, рабочих дней",
                     "по умолчанию 10 — можно изменить, пропись подставится сама"),
    "marketing":  ("Документ", "Маркетинговая кампания",
                   "добавляет пункт 2.1.2 о расходах на SMM"),
    "smm":        ("Документ", "Сумма на SMM, ₽",
                   "полная сумма числом — пропись подставится сама"),
    "penalty":    ("Документ", "Штраф за непереданный трек, ₽",
                   "полная сумма числом — пропись подставится сама"),
    "count":      ("Документ", "Количество треков (обязательство)",
                   "минимальное число треков по обязательству — пропись подставится сама"),
    "delivery_date": ("Документ", "Срок предоставления исходников", ""),

    # Релиз
    "release_type":  ("Релиз", "Тип релиза", ""),
    "release_name":  ("Релиз", "Название релиза", "заполняется для альбома и ЕР"),
    "release_year":  ("Релиз", "Год выпуска", "2026"),
    "has_videoclip": ("Релиз", "Есть видеоклип",
                      "если нет — пункт про клип удалится, нумерация сдвинется"),

    # Таблицы
    "tracks":     ("Треки", "Список треков", ""),
    "videoclips": ("Видеоклипы", "Список видеоклипов", ""),
}

# Значения, которыми поле предзаполняется в форме (в отличие от hint —
# тот только текст-подсказка снизу/бледный placeholder, не реальное
# значение, см. index.html:renderField). Оператор может изменить.
DEFAULT_VALUES = {
    "advance_days": "10",  # срок выплаты аванса, рабочих дней (п.2.2)
    "royalty": "70",       # роялти, % — предзаполнено, оператор может изменить
}

# Поля, которые предзаполняются СЕГОДНЯШНЕЙ датой (не статичным значением
# из DEFAULT_VALUES — дата плывёт день ото дня, поэтому считается заново
# при каждом открытии формы, см. fields_to_dict).
#
# c_date — дата комбинированного Договора. date — дата отдельного
# Приложения/Акта (для них это дата подписания ИМЕННО ЭТОГО документа,
# а не договора-родителя — сегодня естественный дефолт).
#
# НЕ входят: delivery_date (это дедлайн в будущем, не сегодняшняя дата),
# birthday/pas_date (исторические даты контрагента, никак не связаны
# с сегодня).
TODAY_DEFAULT_FIELDS = {"c_date", "date"}

# Приложение/Акт — отдельный файл, привязанный к уже существующему
# договору (см. LINKED_DOC_TYPES выше). У contract/c_date/date там другой
# смысл, чем в комбинированном Договоре, поэтому подпись/подсказка тоже
# другие. FIELD_META общий на все doc_type, поэтому переопределяется
# точечно здесь — по аналогии с LIST_ITEM_LABEL_OVERRIDES для клипа/треков.
LINKED_DOC_FIELD_META = {
    "contract": ("Документ", "Номер договора", ""),
    "date":     ("Документ", "Дата документа",
                 "дата этого Приложения/Акта — может отличаться от даты договора"),
}


def field_meta_for(name: str, doc_type: str | None) -> tuple[str, str, str]:
    """FIELD_META с поправкой на doc_type (см. LINKED_DOC_FIELD_META)."""
    if doc_type in LINKED_DOC_TYPES and name in LINKED_DOC_FIELD_META:
        return LINKED_DOC_FIELD_META[name]
    return FIELD_META.get(name, ("Прочее", name, ""))

# Подписи к колонкам таблиц
ITEM_FIELD_LABELS = {
    "title":         "Название",
    "music_author":  "Автор музыки",
    "lyrics_author": "Автор текста",
    "performer":     "Исполнитель",
    "producer":      "Изготовитель / хронометраж",
    "share_author":  "Доля авторская",
    "share_related": "Доля смежная",
    "director":      "Режиссёр / автор сценария",
    "production":    "Страна / год / хронометраж / возраст",
    "share":         "Доля",
    "nickname":      "Никнейм",
    "fio":           "ФИО",
}

# Некоторые имена полей (music_author, producer) переиспользуются и в
# таблице треков, и в таблице видеоклипов, но означают там разное —
# см. Таблицу №1 и Таблицу №2 в оригинале договора от юриста:
#
#   Треки:  ... Автор музыки | Автор текста | ... | Изготовитель Фонограммы/хронометраж | Доля
#   Клип:   ... Режиссёр/Автор Сценария | Автор музыки/текста | ... | Страна/год/хронометраж/возраст | Изготовитель Видеоклипа | Доля
#
# В клипе это ОДНА колонка "Автор музыки/текста" (без отдельного автора
# текста), а "Изготовитель" — без хронометража (тот в колонке production).
# Общие ITEM_FIELD_LABELS/ITEM_FIELD_ORDER этого не различают (ключ один
# и тот же), поэтому для списка videoclips подписи переопределяются здесь.
LIST_ITEM_LABEL_OVERRIDES = {
    "videoclips": {
        "music_author": "Автор музыки/текста",
        "producer":     "Изготовитель видеоклипа",
    },
    "performers": {
        # тот же смысл, что и "Исполнитель" в таблице треков — псевдоним
        # исполнителя, просто здесь это отдельный список для сноски.
        # Общая подпись "Никнейм" (ITEM_FIELD_LABELS) осталась бы верной
        # по сути, но путает визуально рядом со столбцом "Исполнитель" в
        # соседней таблице треков — оба поля означают одно и то же значение.
        "nickname": "Исполнитель",
    },
}

# Порядок колонок в таблицах. Без этого они идут по алфавиту,
# и «Название» оказывается последним, что неудобно для ввода.
#
# Общий список рассчитан так, чтобы правильно сортировать ОБЕ таблицы
# одновременно (для каждой таблицы берутся только присутствующие в ней
# колонки, остальные просто выпадают из сортировки):
#   Треки:  title, music_author, lyrics_author, performer, producer, share_author, share_related
#   Клип:   title, director, music_author, performer, production, producer, share
# Отсюда director стоит ПЕРЕД music_author (для клипа), а production —
# ПЕРЕД producer (для клипа); на треки это не влияет, т.к. в них нет
# полей director/production.
ITEM_FIELD_ORDER = [
    "title", "director", "music_author", "lyrics_author", "performer",
    "production", "producer", "share_author", "share_related", "share",
    "nickname", "fio",
]

# Порядок полей внутри группы. Отражает порядок в документе,
# а не алфавит: Серия -> Номер -> Кем выдан -> Дата -> КП.
FIELD_ORDER = [
    # Документ (edo — последним в блоке)
    "contract", "c_date", "date", "appendix_no", "act_no", "royalty",
    "advance", "marketing", "smm", "term_end", "edo",
    # Контрагент
    "name", "inn", "nickname",
    # Личные данные (бывший "Паспорт"; npd/birthday — в конце блока)
    "serial", "number", "pas_place", "pas_date", "kp", "npd", "birthday",
    # Контакты
    "adress", "phone", "mail",
    # Реквизиты
    "rs", "bank", "ks", "bik",
    # Релиз
    "release_type", "release_name", "release_year", "has_videoclip",
    # Таблицы
    "tracks", "performers", "videoclips",
]

# Порядок групп в форме
GROUP_ORDER = [
    "Документ", "Контрагент", "Личные данные", "Контакты",
    "Банковские реквизиты", "Релиз", "Треки", "Видеоклипы", "Прочее",
]

# Поля, которые вводятся календарём (<input type="date">) и приходят
# в ISO-формате 2026-03-15. Backend превращает их либо в «15» марта
# 2026 г. (c_date/date/delivery_date, см. format_date_ru), либо в
# точечный формат 15.03.2026 (birthday, pas_date — они печатаются в
# документе как есть, без прописи, см. format_date_dotted).
#
# c_date — всегда календарь. date — календарь ТОЛЬКО для Приложения/Акта
# (LINKED_DOC_TYPES), там это отдельная дата самого документа. Для
# комбинированного Договора date — вычисляемое поле (см. COMPUTED_FIELDS),
# в форме не показывается вовсе, поэтому в базовый набор не входит.
# delivery_date, birthday, pas_date — отдельные самостоятельные даты, не
# привязанные к doc_type, поэтому в базовом наборе, а не в date_fields_for.
# npd НЕ входит — это составное поле (дата + место постановки на учёт
# текстом), в один календарь не сворачивается, остаётся обычным текстом.
DATE_FIELDS = {"c_date", "delivery_date", "birthday", "pas_date"}


def date_fields_for(doc_type: str | None) -> set[str]:
    """DATE_FIELDS с поправкой на doc_type."""
    if doc_type in LINKED_DOC_TYPES:
        return DATE_FIELDS | {"date"}
    return DATE_FIELDS

# Поля, которых НЕТ в шаблоне, но которые нужны context_builder.
# Появляются в форме, только если в шаблоне есть поле-триггер.
#
# Заметь: полей contract_day/month/year и term_quarter/term_year здесь
# НЕТ. Раньше они были, но дублировали то, что уже можно вычислить:
# день/месяц/год договора — из c_date, срок действия (term_end) — теперь
# автоматически из даты документа (+5 лет до конца квартала, см.
# build_term_end в context_builder.py) — оператор больше не выбирает
# квартал/год вручную.
VIRTUAL_FIELDS = [
    # (имя, тип, группа, подпись, подсказка, триггер)
    #
    # is_group раньше был отдельным полем-флагом здесь (один на всю
    # форму — вся таблица считалась либо солистами, либо одной группой).
    # Теперь это чекбокс "Группа" в каждой строке таблицы performers
    # (см. addRow/renderList в index.html — по тому же принципу, что и
    # has_profanity в таблице tracks, чисто фронтенд-колонка, не часть
    # схемы полей). Поддерживает смешанный список: часть исполнителей
    # солисты, часть — участники одной или нескольких групп в одном
    # документе (см. build_performer_note в context_builder.py).
    ("performers",     "list", "Треки", "Исполнители (для сноски)",
     "предзаполняется уникальными исполнителями из таблицы треков — впишите ФИО каждому, отметьте «Группа» для участников группы",
     "performer_note"),
]

# Виртуальных полей типа 'choice' сейчас нет (term_quarter убран — срок
# теперь автоматический), но код ниже (analyze_template) обращается
# к VIRTUAL_CHOICES[vname] для любого виртуального choice-поля, если
# оно появится в будущем — оставляем пустым, а не удаляем совсем.
VIRTUAL_CHOICES: dict[str, list[tuple[str, str]]] = {}

VIRTUAL_LIST_ITEMS = {
    "performers": ["nickname", "fio"],
}


@dataclass
class FormField:
    """Описание одного поля формы."""
    name: str
    type: str                       # 'text' | 'date' | 'flag' | 'choice' | 'list'
    # для type='list' — колонки элемента списка
    item_fields: list[str] = field(default_factory=list)
    # для type='choice' — значения и подписи к ним
    choices: list[str] = field(default_factory=list)
    choice_labels: list[str] = field(default_factory=list)


def _extract_text(docx_bytes: bytes) -> str:
    """
    Достаёт текст всех XML-частей документа (тело + колонтитулы),
    убирая теги Word. Метки могут стоять и в колонтитулах.
    """
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        parts = [
            n for n in z.namelist()
            if n.endswith(".xml") and any(k in n for k in ("document", "header", "footer"))
        ]
        raw = "".join(z.read(p).decode("utf-8", "ignore") for p in parts)
    # вырезаем XML-теги: остаётся чистый текст с метками Jinja
    text = re.sub(r"<[^>]+>", "", raw)
    # XML-сущности (&gt; &lt; &amp;) — если в условии шаблона встретился
    # символ > (напр. "{% if tracks|length > 1 %}"), Word при сохранении
    # экранирует его как "&gt;". Не разэкранировав, регексы ниже видят
    # только часть условия и по ошибке принимают обрывок ("gt") за
    # отдельную переменную — этот баг уже случался. Разэкранируем сразу,
    # чтобы анализ работал с тем же текстом, что видит Jinja при рендере.
    text = text.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")
    return text


def analyze_template(docx_bytes: bytes, doc_type: str | None = None) -> list[FormField]:
    """
    Возвращает описание полей формы, выведенное из разметки шаблона.

    doc_type шаблона ('contract' | 'appendix' | 'act' | None) влияет на
    трактовку contract/c_date/date — см. computed_fields_for() и
    date_fields_for() выше: для отдельных Приложения/Акта (LINKED_DOC_TYPES)
    contract и date становятся обычными полями ввода вместо вычисляемых.

    Порядок определения типа (важен — от специфичного к общему):
      1. list   — переменная участвует в {% for x in ЭТО %}
      2. choice — сравнивается со строковым литералом: ЭТО != 'none'
      3. flag   — используется ТОЛЬКО в условиях, нигде не выводится как {{ }}
      4. text   — всё остальное
    """
    text = _extract_text(docx_bytes)
    computed = computed_fields_for(doc_type)
    date_fields = date_fields_for(doc_type)

    # --- 1. Списки и колонки их элементов ---
    # {%tr for t in tracks %} / {%p for %} / {% for %}
    loops = re.findall(r"\{%\s*(?:tr\s+|p\s+)?for\s+(\w+)\s+in\s+(\w+)\s*%\}", text)

    lists: dict[str, list[str]] = {}
    loop_vars = set()
    for item_var, collection in loops:
        loop_vars.add(item_var)
        # колонки: {{ t.title }} -> title
        attrs = set(re.findall(rf"\{{\{{\s*{re.escape(item_var)}\.(\w+)", text))
        lists[collection] = sorted(attrs)

    # --- 2. Переменные, выводимые как {{ x }} (без точки) ---
    printed = set(re.findall(r"\{\{\s*(\w+)\s*\}\}", text))
    printed -= JINJA_BUILTINS
    printed -= loop_vars  # {{ t }} сам по себе не поле

    # --- 3. Переменные в условиях ---
    cond_bodies = re.findall(r"\{%\s*(?:tr\s+|p\s+)?if\s+([^%]+?)\s*%\}", text)

    in_conditions: set[str] = set()
    choices: dict[str, set[str]] = {}

    for body in cond_bodies:
        # сначала вытаскиваем сравнения со строковыми литералами:
        #   release_type != 'none'  ->  choices['release_type'] = {'none'}
        for var, val in re.findall(r"(\w+)\s*[!=]=\s*'([^']*)'", body):
            choices.setdefault(var, set()).add(val)

        # затем УБИРАЕМ литералы из текста условия, иначе 'none' будет
        # распознан как имя переменной и попадёт в форму отдельным полем
        body_no_literals = re.sub(r"'[^']*'", "", body)

        names = set(re.findall(r"\b([a-zA-Z_]\w*)\b", body_no_literals))
        names -= {"not", "and", "or", "in", "is", "length", "None", "True", "False"}
        in_conditions |= names

    # --- Собираем результат ---
    fields: list[FormField] = []

    # все переменные шаблона (для решения, какие виртуальные поля нужны)
    all_vars = printed | in_conditions | set(lists)
    computed_present = all_vars & computed

    # списки
    for name, item_fields in sorted(lists.items()):
        fields.append(FormField(name=name, type="list", item_fields=item_fields))

    # остальные переменные
    others = (printed | in_conditions) - set(lists) - computed - JINJA_BUILTINS
    for name in sorted(others):
        if name in KNOWN_CHOICES:
            # полный список вариантов задан явно (шаблон знает не все)
            fields.append(FormField(
                name=name, type="choice",
                choices=[v for v, _ in KNOWN_CHOICES[name]],
                choice_labels=[l for _, l in KNOWN_CHOICES[name]],
            ))
        elif name in choices:
            vals = sorted(choices[name])
            fields.append(FormField(name=name, type="choice", choices=vals,
                                    choice_labels=vals))
        elif name in in_conditions and name not in printed:
            # используется только в {% if %}, нигде не выводится -> флаг
            fields.append(FormField(name=name, type="flag"))
        elif name in date_fields:
            # календарь: ISO на входе, русский текст в документе
            fields.append(FormField(name=name, type="date"))
        else:
            fields.append(FormField(name=name, type="text"))

    # --- виртуальные поля ---
    # Добавляем те, чей триггер (вычисляемая метка) есть в шаблоне.
    # Пример: если шаблон содержит {{ contract }}, значит нужны поля
    # день/месяц/год, из которых context_builder соберёт номер.
    for vname, vtype, _grp, _lbl, _hint, trigger in VIRTUAL_FIELDS:
        if trigger not in computed_present:
            continue
        f = FormField(name=vname, type=vtype)
        if vtype == "choice":
            f.choices = [v for v, _ in VIRTUAL_CHOICES[vname]]
            f.choice_labels = [l for _, l in VIRTUAL_CHOICES[vname]]
        if vtype == "list":
            f.item_fields = VIRTUAL_LIST_ITEMS[vname]
        fields.append(f)

    return fields


def fields_to_dict(fields: list[FormField], doc_type: str | None = None) -> list[dict]:
    """
    Приводит к JSON-виду для фронтенда: добавляет группу, подпись, подсказку.
    Поля отсортированы по порядку групп (GROUP_ORDER).

    doc_type пробрасывается в field_meta_for() — для contract/c_date/date
    подпись и подсказка зависят от типа шаблона (см. LINKED_DOC_FIELD_META).
    """
    out = []
    virtual_meta = {v[0]: (v[2], v[3], v[4]) for v in VIRTUAL_FIELDS}

    for f in fields:
        if f.name in virtual_meta:
            group, label, hint = virtual_meta[f.name]
        else:
            group, label, hint = field_meta_for(f.name, doc_type)

        if f.name in TODAY_DEFAULT_FIELDS and f.type == "date":
            default = _date.today().isoformat()  # 2026-07-12 — ISO, как ждёт <input type="date">
        else:
            default = DEFAULT_VALUES.get(f.name, "")

        item = {
            "name": f.name,
            "type": f.type,
            "group": group,
            "label": label,
            "hint": hint,
            "default": default,
        }
        if f.type == "list":
            # колонки в осмысленном порядке, а не по алфавиту
            col_order = {c: i for i, c in enumerate(ITEM_FIELD_ORDER)}
            cols = sorted(f.item_fields, key=lambda c: col_order.get(c, 999))
            overrides = LIST_ITEM_LABEL_OVERRIDES.get(f.name, {})
            item["item_fields"] = [
                {"name": c, "label": overrides.get(c, ITEM_FIELD_LABELS.get(c, c))}
                for c in cols
            ]
        if f.type == "choice":
            item["choices"] = [
                {"value": v, "label": l}
                for v, l in zip(f.choices, f.choice_labels or f.choices)
            ]
        out.append(item)

    # сортируем: сначала по порядку групп, внутри группы — по FIELD_ORDER
    group_pos = {g: i for i, g in enumerate(GROUP_ORDER)}
    field_pos = {f: i for i, f in enumerate(FIELD_ORDER)}
    out.sort(key=lambda x: (group_pos.get(x["group"], 999),
                            field_pos.get(x["name"], 999)))
    return out
