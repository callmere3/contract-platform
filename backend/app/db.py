"""
Подключение к PostgreSQL через SQLAlchemy.

Этап 2: добавлены session-фабрика (для работы с БД в эндпоинтах) и
init_db() — создание таблиц. На этом этапе используем create_all() для
простоты; полноценные миграции через Alembic имеет смысл подключить позже,
когда схема стабилизируется и появятся изменения существующих таблиц.
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
