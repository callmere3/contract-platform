"""
Подключение к PostgreSQL через SQLAlchemy.

На этапе 1 нам не нужны ни модели таблиц, ни миграции — только доказать,
что backend умеет достучаться до базы. Модели и Alembic появятся на этапе 2,
когда будем проектировать реальные таблицы (templates, counterparties и т.д.)
"""
from sqlalchemy import create_engine, text

from app.config import settings

# pool_pre_ping=True — перед каждым использованием соединения из пула
# SQLAlchemy проверяет, что оно живое. Без этого можно словить ошибку
# "connection closed", если Postgres перезапускался, а пул этого не заметил.
engine = create_engine(settings.database_url, pool_pre_ping=True)


def check_db_connection() -> bool:
    """Простейшая проверка связи — выполняет SELECT 1 и не падает."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
