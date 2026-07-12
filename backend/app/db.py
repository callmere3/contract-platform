"""
Подключение к PostgreSQL через SQLAlchemy.

Схема БД теперь версионируется через Alembic (см. backend/alembic/) —
любое изменение структуры (новая таблица, ALTER TABLE ADD COLUMN и т.п.)
оформляется отдельной ревизией и накатывается командой
`alembic upgrade head`, а не через DROP+пересоздание таблиц.

init_db()/create_all() оставлены только для самого первого локального
поднятия проекта с нуля (пустая БД, ни одной ревизии ещё не накатано —
create_all() создаст все таблицы сразу по текущим models.py). На сервере,
где уже есть данные, всегда используем `alembic upgrade head`, не init_db().
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Base

engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Создаёт таблицы, которых ещё нет. Существующие не трогает."""
    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    """FastAPI-зависимость: выдаёт сессию БД и гарантированно закрывает её."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def check_db_connection() -> bool:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
