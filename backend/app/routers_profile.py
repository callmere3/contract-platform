"""
Карточка профиля — то, что человек видит, нажав на своё имя в шапке.

  GET /profile/achievements — достижения ТЕКУЩЕГО пользователя.

Только свои: user_id параметром не принимается вовсе. Достижения — вещь
личная, и подглядывать за чужими через подбор id не должно быть возможно
даже теоретически. Кому нужна общая картина — есть вкладка «Кубок» у
админа.

Имя, роль и кубок у имени фронт уже знает из /auth/me — сюда они не
дублируются.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.achievements import user_achievements
from app.auth import get_current_user
from app.db import get_session
from app.models import User

profile_router = APIRouter(prefix="/profile", tags=["profile"])


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
    return {"achievements": user_achievements(db, current_user)}
