"""
Достижения в карточке профиля (значки у имени — см. app/champion.py).

Считаются на лету из истории генерации и журнала выданных токенов:
отдельной таблицы наград нет, как и у кубка. Плюс в том, что достижение
можно добавить задним числом — оно сразу учтёт всю прошлую работу.

Состав (по решению владельца 16.09.2026):
  🏆 Кубок месяца   — сколько раз человек был чемпионом месяца;
  📄 Вехи           — 1 / 10 / 25 / 50 / 100 уникальных документов за всё время;
  🤖 Машина         — 10 уникальных документов за ОДИН день;
  💎 Алмаз          — СЕКРЕТНОЕ: вернуться после перерыва больше 100 дней.

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

from app.champion import MSK, _document_key, as_utc, champion_history
from app.models import GeneratedDocument, RefreshToken, User

# Вехи по документам. Первая намеренно равна 1: у семи учёток из десяти
# сейчас ноль документов, и без достижимой первой ступени раздел у них был
# бы сплошь серым.
DOC_MILESTONES = (
    (1, "📄", "Первый документ"),
    (10, "📚", "10 документов"),
    (25, "🗄️", "25 документов"),
    (50, "⭐", "50 документов"),
    (100, "💯", "100 документов"),
)

MACHINE_TARGET = 10     # уникальных документов за один день
DIAMOND_DAYS = 100      # перерыв между заходами


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
        .filter(RefreshToken.user_id == user_id)
        .order_by(RefreshToken.created_at)
        .all()
    ]
    if len(stamps) < 2:
        return 0
    return max(
        int((later - earlier).total_seconds() // 86400)
        for earlier, later in zip(stamps, stamps[1:])
    )


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
    rows = (
        db.query(GeneratedDocument).filter(GeneratedDocument.user_id == user.id).all()
    )

    unique_keys = {_document_key(row) for row in rows}
    total = len(unique_keys)

    per_day: dict = {}
    for row in rows:
        day = as_utc(row.created_at).astimezone(MSK).date()
        per_day.setdefault(day, set()).add(_document_key(row))
    best_day = max((len(keys) for keys in per_day.values()), default=0)

    cups = champion_history(db).get(user.id, [])

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
            subtitle=", ".join(cups) if cups else None,
            count=len(cups) if cups else None,
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
            icon="🤖",
            title="Машина",
            hint="10 документов за один день",
            earned=best_day >= MACHINE_TARGET,
            subtitle=("рекорд — %d за день" % best_day) if best_day >= MACHINE_TARGET else None,
            progress=None if best_day >= MACHINE_TARGET else {"current": best_day, "target": MACHINE_TARGET},
        )
    )

    # 💎 Секретное. Пока не получено — наружу уходит «замок» без условия и
    # без прогресса: подсказка «вам осталось не заходить 40 дней» убила бы
    # и секрет, и смысл.
    diamond_earned = longest_absence_days(db, user.id) >= DIAMOND_DAYS
    if diamond_earned:
        diamond = _achievement(
            code="diamond",
            icon="💎",
            title="Алмаз",
            hint="Вернуться в сервис после перерыва больше 100 дней",
            earned=True,
            subtitle="перерыв больше 100 дней",
        )
    else:
        diamond = _achievement(
            code="diamond",
            icon="🔒",
            title="Секретное достижение",
            hint="Условие скрыто",
            earned=False,
        )
    diamond["secret"] = True
    out.append(diamond)

    return out
