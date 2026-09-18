"""
Карточка профиля — то, что человек видит, нажав на своё имя в шапке.

  GET  /profile/achievements — достижения ТЕКУЩЕГО пользователя.
  POST /profile/events       — отметить действие, которого не видно в данных.

Только свои: user_id параметром не принимается вовсе. Достижения — вещь
личная, и подглядывать за чужими через подбор id не должно быть возможно
даже теоретически. Кому нужна общая картина — есть вкладка «Кубок» у
админа.

Имя, роль и кубок у имени фронт уже знает из /auth/me — сюда они не
дублируются.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.achievements import honorary_note, user_achievements
from app.auth import get_current_user
from app.db import get_session
from app.models import User, UserEvent

profile_router = APIRouter(prefix="/profile", tags=["profile"])

# Какие события клиент вправе отмечать. Белый список, а не любая строка:
# имя приходит из браузера, и без него в таблицу можно было бы насыпать
# произвольного мусора. Добавили достижение на новом действии — дописали
# сюда строку.
ALLOWED_EVENTS = {"draft_discarded"}


class EventReport(BaseModel):
    event: str


@profile_router.get("/achievements")
def my_achievements(
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    {"achievements": [{code, icon, title, hint, subtitle, earned, progress,
    count, secret}, …]} — и полученные, и ещё нет (у вторых заполнен
    progress). Секретное, пока не получено, приходит «замком» без условия.
    """
    return {
        "achievements": user_achievements(db, current_user),
        # Подпись над списком — у почётных учёток (см. achievements.py).
        "note": honorary_note(current_user),
    }


@profile_router.post("/events")
def report_event(
    body: EventReport,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Отметить действие, которого не видно в данных: сейчас — сброшенный
    черновик (достижение «Разбитое сердце»).

    Только за себя: user_id берётся из токена, параметром его не передать.
    Событие пишется каждый раз, без дедупликации — достижению хватает
    факта «было хоть раз», а история кликов может пригодиться потом.
    """
    if body.event not in ALLOWED_EVENTS:
        raise HTTPException(status_code=400, detail="Неизвестное событие")

    db.add(UserEvent(user_id=current_user.id, event=body.event))
    db.commit()
    return {"ok": True}
