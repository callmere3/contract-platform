"""
Достижения в карточке профиля (значки у имени — см. app/champion.py).

Считаются на лету из истории генерации и журнала выданных токенов:
отдельной таблицы наград нет, как и у кубка. Плюс в том, что достижение
можно добавить задним числом — оно сразу учтёт всю прошлую работу.

Состав:
  🏆 Кубок месяца        — сколько раз человек был чемпионом месяца;
  👑 Король квартала     — три победы в трёх месяцах подряд;
  📄 Вехи                — 1 / 10 / 25 / 50 / 100 документов за всё время:
                           «Проба пера», «Стопка бумаг», «Небольшой архив»,
                           «Звезда документооборота», «Сотка!»;
  🚗 Машина              — 10 уникальных документов за ОДИН день;
  🚀 Ракета              — то же, но двадцать;
  🌙 Ночная смена        — документ между 22:00 и 6:00 по Москве;
  🧠 Знает все шаблоны   — сделал и договор, и приложение, и акт;
  👻 Призрак             — СЕКРЕТНОЕ: вернуться после перерыва больше 100 дней.

Что считается одним документом — то же правило, что у кубка
(`_document_key`): формат не в счёт, один и тот же документ в Word и в PDF
— один документ. Иначе достижения и кубок считали бы по-разному, и человек
с «10 документами за день» не понимал бы, почему в рейтинге у него другое
число.

Незаработанные достижения показываются с прогрессом (решение владельца),
поэтому здесь возвращаются ВСЕ, а не только полученные. Исключение —
секретное: пока не получено, наружу уходит только «замок» без условия,
иначе никакого секрета не остаётся.
"""
from sqlalchemy.orm import Session

from app.champion import MSK, _document_key, as_utc, champion_history, scoring_since
from app.models import GeneratedDocument, RefreshToken, Template, User

# Вехи по документам. Первая намеренно равна 1: у семи учёток из десяти
# сейчас ноль документов, и без достижимой первой ступени раздел у них был
# бы сплошь серым.
#
# Названия — не описания: сколько документов нужно, написано в подсказке
# (hint), она же видна при наведении и в окне достижения. Менять название,
# не поправив подсказку, нельзя — тогда условие потеряется совсем.
DOC_MILESTONES = (
    (1, "📝", "Проба пера"),
    (10, "📚", "Стопка бумаг"),
    (25, "🗄️", "Небольшой архив"),
    (50, "⭐", "Звезда документооборота"),
    (100, "💯", "Сотка!"),
)

MACHINE_TARGET = 10     # «Машина» — уникальных документов за один день
ROCKET_TARGET = 20      # «20 за день» — то же, но вдвое больше
CUP_STREAK_TARGET = 3   # «Три кубка подряд»
GHOST_DAYS = 100        # «Призрак» — перерыв между заходами

# «Ночная смена»: документ, сделанный с 22:00 до 6:00 по Москве. Границы
# заданы явно и в подсказке к достижению написаны теми же числами — иначе
# человек не поймёт, почему ночной документ не засчитался.
NIGHT_FROM_HOUR = 22
NIGHT_TO_HOUR = 6

# «Знает все шаблоны» — по одному документу каждого типа. Значения те же,
# что в Template.doc_type (см. models.py), а не выдуманные здесь.
ALL_DOC_TYPES = ("contract", "appendix", "act")


def longest_absence_days(db: Session, user_id) -> int:
    """
    Самый длинный перерыв между заходами в сервис, в днях.

    Считается по refresh_tokens: строка появляется и при входе, и при
    продлении сессии, поэтому внутри рабочего дня они идут густо, а
    отсутствие видно как разрыв. Строки не удаляются никогда (logout лишь
    помечает revoked_at), так что история полная.

    Именно ПЕРЕРЫВ МЕЖДУ заходами, а не «сколько не заходит сейчас»:
    достижение выдаётся тому, кто вернулся, а вернувшийся уже создал новую
    строку — разрыв попадает в выборку сам.
    """
    stamps = [
        as_utc(t.created_at)
        for t in db.query(RefreshToken)
        .filter(
            RefreshToken.user_id == user_id,
            # Заходы до сброса зачёта не считаются — как и всё остальное.
            RefreshToken.created_at >= scoring_since(),
        )
        .order_by(RefreshToken.created_at)
        .all()
    ]
    if len(stamps) < 2:
        return 0
    return max(
        int((later - earlier).total_seconds() // 86400)
        for earlier, later in zip(stamps, stamps[1:])
    )


def _longest_cup_streak(months: list) -> int:
    """
    Самая длинная серия побед в идущих подряд месяцах.

    Считается по (год, месяц) из champion_history, а не по подписям: между
    «декабрём 2026» и «январём 2027» разрыва нет, и арифметика месяцев это
    знает, а сравнение строк — нет.
    """
    best = 0
    run = 0
    previous = None
    for year, month, _label in months:
        following = previous is not None and (year, month) == (
            (previous[0], previous[1] + 1) if previous[1] < 12 else (previous[0] + 1, 1)
        )
        run = run + 1 if following else 1
        previous = (year, month)
        best = max(best, run)
    return best


def _achievement(code, icon, title, hint, earned, subtitle=None, progress=None, count=None):
    return {
        "code": code,
        "icon": icon,
        "title": title,
        "hint": hint,            # как получить — показывается всегда
        "subtitle": subtitle,    # что именно получено — только у заработанных
        "earned": earned,
        "progress": progress,    # {"current": 3, "target": 10} у незаработанных
        "count": count,          # для повторяемых (кубки)
        "secret": False,
    }


def user_achievements(db: Session, user: User) -> list[dict]:
    """Все достижения пользователя — и полученные, и ещё нет."""
    # Только работа ПОСЛЕ момента сброса (SCORING_SINCE в champion.py):
    # 16.09.2026 значки обнулили, чтобы их заработали заново. Рубеж здесь
    # ТОЧНЫЙ, в отличие от кубка: достижения накопительные и ничьего месяца
    # не делят, поэтому резать их по календарю незачем.
    rows = (
        db.query(GeneratedDocument)
        .filter(
            GeneratedDocument.user_id == user.id,
            GeneratedDocument.created_at >= scoring_since(),
        )
        .all()
    )

    unique_keys = {_document_key(row) for row in rows}
    total = len(unique_keys)

    per_day: dict = {}
    for row in rows:
        day = as_utc(row.created_at).astimezone(MSK).date()
        per_day.setdefault(day, set()).add(_document_key(row))
    best_day = max((len(keys) for keys in per_day.values()), default=0)

    # Ночь — по московскому времени: у человека в браузере может быть любой
    # часовой пояс, а «ночная смена» — про то, когда он реально работал.
    night = any(
        as_utc(row.created_at).astimezone(MSK).hour >= NIGHT_FROM_HOUR
        or as_utc(row.created_at).astimezone(MSK).hour < NIGHT_TO_HOUR
        for row in rows
    )

    # Типы документов берём из шаблонов: в истории генерации лежит только
    # template_id. У удалённого шаблона связь обнулена (SET NULL) — такой
    # документ в зачёт типов не идёт, восстановить его тип неоткуда.
    template_ids = {row.template_id for row in rows if row.template_id}
    covered_types = set()
    if template_ids:
        covered_types = {
            t.doc_type
            for t in db.query(Template).filter(Template.id.in_(template_ids)).all()
            if t.doc_type in ALL_DOC_TYPES
        }

    cups = champion_history(db).get(user.id, [])
    cup_labels = [label for _year, _month, label in cups]
    cup_streak = _longest_cup_streak(cups)

    out = []

    # 🏆 Кубки месяца. Прогресса нет намеренно: к кубку нельзя «пройти
    # половину пути» — он либо взят за месяц, либо нет.
    out.append(
        _achievement(
            code="champion",
            icon="🏆",
            title="Кубок месяца",
            hint="Больше всех документов за календарный месяц",
            earned=bool(cups),
            subtitle=", ".join(cup_labels) if cups else None,
            count=len(cups) if cups else None,
        )
    )

    out.append(
        _achievement(
            code="cup_streak",
            icon="👑",
            title="Король квартала",
            hint="Быть чемпионом три месяца подряд",
            earned=cup_streak >= CUP_STREAK_TARGET,
            subtitle=None,
            progress=None
            if cup_streak >= CUP_STREAK_TARGET
            else {"current": cup_streak, "target": CUP_STREAK_TARGET},
        )
    )

    for target, icon, title in DOC_MILESTONES:
        earned = total >= target
        out.append(
            _achievement(
                code="docs_%d" % target,
                icon=icon,
                title=title,
                hint="Сформировать %d %s за всё время"
                % (target, "документ" if target == 1 else "документов"),
                earned=earned,
                subtitle=None,
                progress=None if earned else {"current": total, "target": target},
            )
        )

    out.append(
        _achievement(
            code="machine",
            icon="🚗",
            title="Машина",
            hint="10 документов за один день",
            earned=best_day >= MACHINE_TARGET,
            subtitle=("рекорд — %d за день" % best_day) if best_day >= MACHINE_TARGET else None,
            progress=None if best_day >= MACHINE_TARGET else {"current": best_day, "target": MACHINE_TARGET},
        )
    )

    out.append(
        _achievement(
            code="rocket",
            icon="🚀",
            title="Ракета",
            hint="20 документов за один день",
            earned=best_day >= ROCKET_TARGET,
            subtitle=("рекорд — %d за день" % best_day) if best_day >= ROCKET_TARGET else None,
            progress=None
            if best_day >= ROCKET_TARGET
            else {"current": best_day, "target": ROCKET_TARGET},
        )
    )

    out.append(
        _achievement(
            code="night",
            icon="🌙",
            title="Ночная смена",
            hint="Сформировать документ между 22:00 и 6:00",
            earned=night,
        )
    )

    out.append(
        _achievement(
            code="all_types",
            icon="🧠",
            title="Знает все шаблоны",
            hint="Сделать договор, приложение и акт",
            earned=len(covered_types) == len(ALL_DOC_TYPES),
            subtitle=None,
            progress=None
            if len(covered_types) == len(ALL_DOC_TYPES)
            else {"current": len(covered_types), "target": len(ALL_DOC_TYPES)},
        )
    )

    # 👻 Секретное. Пока не получено — наружу уходит «замок» без условия и
    # без прогресса: подсказка «вам осталось не заходить 40 дней» убила бы
    # и секрет, и смысл.
    ghost_earned = longest_absence_days(db, user.id) >= GHOST_DAYS
    if ghost_earned:
        ghost = _achievement(
            code="ghost",
            icon="👻",
            title="Призрак",
            hint="Вернуться в сервис после перерыва больше 100 дней",
            earned=True,
            subtitle="перерыв больше 100 дней",
        )
    else:
        ghost = _achievement(
            code="ghost",
            icon="🔒",
            title="Секретное достижение",
            hint="Условие скрыто",
            earned=False,
        )
    ghost["secret"] = True
    out.append(ghost)

    return out
