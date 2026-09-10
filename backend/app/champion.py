"""
«Кубок месяца» — значок у того, кто за ПРОШЛЫЙ календарный месяц сделал
больше всех уникальных документов.

ЧТО СЧИТАЕТСЯ ОДНИМ ДОКУМЕНТОМ. Ключ — тройка (шаблон, контрагент,
содержимое формы). Формат (docx/pdf) в ключ НЕ входит: один и тот же
документ, выгруженный и в Word, и в PDF, — это один документ, ровно как
просил владелец. Повторная выгрузка того же самого (например, второй раз
docx) по той же причине не добавляет счётчику ничего: содержимое формы
совпадает. А вот та же связка «шаблон + контрагент» с ДРУГИМИ данными —
это отдельный документ, и так и задумано: менеджеры закрывают старые долги
по документам, и десяток приложений одному контрагенту с разными данными
за месяц — нормальная работа, а не накрутка.

КТО УЧАСТВУЕТ. Все роли, кроме admin (NOT_COMPETING): админская учётка
служебная, ею заводят и проверяют, а не работают. Ничья не разрешается в
пользу кого-то одного — кубок получают все, у кого одинаковый максимум.
Если за месяц не сгенерировано ничего, чемпиона нет, и значок не
показывается ни у кого.

ПОЧЕМУ НЕ ХРАНИМ В БАЗЕ. Итог месяца однозначно выводится из
generated_documents, поэтому ни таблицы наград, ни задачи по расписанию не
нужно: 1-го числа в 00:00 по Москве победитель меняется сам собой. Меньше
движущихся частей — нечему разъехаться с данными.

ПОЧЕМУ УНИКАЛЬНОСТЬ СЧИТАЕТСЯ В PYTHON, А НЕ В SQL. В Postgres это был бы
DISTINCT по jsonb-payload — а он большой (данные формы со списком треков),
и сортировка таких значений дорога. Здесь вместо этого берётся sha1 от
канонического JSON. Заодно работает и на SQLite (локальный прогон без
Docker), где нет ни md5(), ни jsonb.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import GeneratedDocument, User
from app.roles import ADMIN

# Москва: UTC+3 круглый год — перевод часов в России отменён в 2014-м.
# Фиксированное смещение вместо ZoneInfo намеренно: не тянем tzdata ради
# зоны, которая не меняется (на Windows её пришлось бы ставить пакетом).
MSK = timezone(timedelta(hours=3))

# Роли вне конкурса. Вынесено отдельной константой: добавить/убрать роль —
# одна строка, без правки логики.
NOT_COMPETING = (ADMIN,)

_MONTHS_RU = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)
# Родительный падеж — для «чемпион августа 2026». Отдельным списком, а не
# правилом отсечения окончания: у «март/мая» оно разное, а склонять строку
# кодом ради двенадцати слов не стоит.
_MONTHS_RU_OF = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

# Итог закрытого месяца уже не меняется (разве что админ удалит записи
# истории), а список пользователей опрашивается фронтом раз в 30 секунд —
# поэтому держим короткий кеш, чтобы не пересчитывать на каждый опрос.
# Ключ кеша — сам месяц, так что смена месяца сбрасывает его сама.
# Рейтинг ТЕКУЩЕГО месяца не кешируется: он меняется в течение дня.
_CACHE_TTL_SECONDS = 600
_cache: dict = {"period": None, "computed_at": None, "value": None}


def _labels(moment: datetime) -> tuple[str, str]:
    """(«август 2026», «августа 2026») для месяца, в котором лежит moment."""
    return (
        "%s %d" % (_MONTHS_RU[moment.month - 1], moment.year),
        "%s %d" % (_MONTHS_RU_OF[moment.month - 1], moment.year),
    )


def current_month_bounds(now: datetime | None = None) -> tuple[datetime, datetime, str, str]:
    """Границы ТЕКУЩЕГО месяца по Москве (в UTC) и его названия."""
    now_utc = now or datetime.now(timezone.utc)
    now_msk = now_utc.astimezone(MSK)
    first_of_this = now_msk.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    label, label_of = _labels(first_of_this)
    return first_of_this.astimezone(timezone.utc), now_utc, label, label_of


def previous_month_bounds(now: datetime | None = None) -> tuple[datetime, datetime, str, str]:
    """
    Границы прошлого календарного месяца по московскому времени и его
    названия. Границы возвращаются в UTC — created_at хранится с таймзоной,
    сравнение идёт в UTC.
    """
    now_utc = now or datetime.now(timezone.utc)
    now_msk = now_utc.astimezone(MSK)

    first_of_this = now_msk.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # «День до первого числа» — надёжнее арифметики с номерами месяцев:
    # сам обрабатывает декабрь→январь и разную длину месяцев.
    some_day_of_prev = first_of_this - timedelta(days=1)
    first_of_prev = some_day_of_prev.replace(hour=0, minute=0, second=0, microsecond=0, day=1)

    label, label_of = _labels(first_of_prev)
    return first_of_prev.astimezone(timezone.utc), first_of_this.astimezone(timezone.utc), label, label_of


def _document_key(row) -> tuple:
    """Что считаем одним документом: шаблон + контрагент + содержимое формы."""
    payload_fingerprint = hashlib.sha1(
        json.dumps(row.payload or {}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return (str(row.template_id), str(row.contragent_id), payload_fingerprint)


def unique_counts(db: Session, start: datetime, end: datetime) -> dict:
    """
    {user_id: сколько уникальных документов} за период [start, end).
    Роли вне конкурса и записи без автора отброшены.
    """
    rows = (
        db.query(GeneratedDocument)
        .filter(GeneratedDocument.created_at >= start, GeneratedDocument.created_at < end)
        .all()
    )
    out_of_contest = {u.id for u in db.query(User).filter(User.role.in_(NOT_COMPETING)).all()}

    per_user: dict = {}
    for row in rows:
        if row.user_id is None or row.user_id in out_of_contest:
            continue
        per_user.setdefault(row.user_id, set()).add(_document_key(row))
    return {user_id: len(keys) for user_id, keys in per_user.items()}


def month_champions(db: Session, now: datetime | None = None) -> dict | None:
    """
    Чемпион(ы) прошлого месяца: {"period": "август 2026", "period_of":
    "августа 2026", "documents": 21, "user_ids": {UUID, ...}} либо None,
    если месяц пустой.
    """
    start, end, label, label_of = previous_month_bounds(now)

    cached = _cache
    if (
        cached["period"] == label
        and cached["computed_at"] is not None
        and (datetime.now(timezone.utc) - cached["computed_at"]).total_seconds() < _CACHE_TTL_SECONDS
    ):
        return cached["value"]

    counts = unique_counts(db, start, end)

    value = None
    if counts:
        best = max(counts.values())
        if best > 0:
            value = {
                "period": label,
                "period_of": label_of,
                "documents": best,
                # Ничья — кубок у всех, кто набрал максимум.
                "user_ids": {uid for uid, n in counts.items() if n == best},
            }

    _cache.update({"period": label, "computed_at": datetime.now(timezone.utc), "value": value})
    return value


def champion_badge(champions: dict | None, user_id) -> dict | None:
    """Блок для выдачи в API: чемпион ли ЭТОТ пользователь, и с каким счётом."""
    if not champions or user_id not in champions["user_ids"]:
        return None
    return {
        "period": champions["period"],
        "period_of": champions["period_of"],
        "documents": champions["documents"],
    }
