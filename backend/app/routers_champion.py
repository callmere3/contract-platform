"""
Вкладка «Кубок» (только Admin).

  GET /champion  — кто носит кубок сейчас (победитель ПРОШЛОГО месяца) и
                   рейтинг ТЕКУЩЕГО месяца, то есть кто идёт на кубок
                   следующим.

Почему два разных месяца в одном ответе: значок у имени показывает итог
закрытого месяца (он уже не изменится), а смотреть интересно за гонкой,
которая идёт прямо сейчас. Разводить это по двум запросам незачем —
страница всё равно показывает оба блока сразу.

Правила подсчёта и состав участников — в app/champion.py, здесь только
выдача. Считается на лету из generated_documents: таблицы наград нет.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_role
from app.champion import current_month_bounds, month_champions, unique_counts
from app.db import get_session
from app.models import User
from app.roles import CAN_VIEW_CHAMPION_BOARD

champion_router = APIRouter(prefix="/champion", tags=["champion"])


def _person(user: User, documents: int) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "full_name": user.full_name,
        "documents": documents,
    }


@champion_router.get("", dependencies=[Depends(require_role(*CAN_VIEW_CHAMPION_BOARD))])
def champion_board(db: Session = Depends(get_session)) -> dict:
    """
    {
      "current": {"period", "period_of", "documents", "winners": [...]} | null,
      "rating":  {"period", "period_of", "rows": [...]}
    }

    winners — список, а не один человек: при ничьей кубок у всех.
    rows отсортированы по убыванию; пустой список — за этот месяц ещё никто
    ничего не сформировал (нормальное состояние 1-го числа).
    """
    users = {u.id: u for u in db.query(User).all()}

    champions = month_champions(db)
    current = None
    if champions:
        current = {
            "period": champions["period"],
            "period_of": champions["period_of"],
            "documents": champions["documents"],
            "winners": [
                _person(users[uid], champions["documents"])
                for uid in champions["user_ids"]
                if uid in users
            ],
        }

    start, end, label, label_of = current_month_bounds()
    counts = unique_counts(db, start, end)
    rows = [_person(users[uid], n) for uid, n in counts.items() if uid in users]
    # По убыванию документов, при равенстве — по имени, чтобы порядок не
    # прыгал между обновлениями страницы.
    rows.sort(key=lambda r: (-r["documents"], (r["full_name"] or r["username"]).lower()))

    return {
        "current": current,
        "rating": {"period": label, "period_of": label_of, "rows": rows},
    }
