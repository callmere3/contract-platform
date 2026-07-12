"""
Конфигурация Alembic.

Важно: URL базы и метаданные моделей берём из самого приложения
(app.config.settings, app.models.Base), а не дублируем их в alembic.ini —
так одна и та же DATABASE_URL из .env работает и для uvicorn, и для
`alembic upgrade head`, и не разъедется при смене окружения (dev/prod).
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# alembic запускается из backend/ (см. alembic.ini: script_location = alembic),
# поэтому пакет app уже виден без правки sys.path
from app.config import settings
from app.models import Base

config = context.config

# подставляем реальный URL из настроек приложения вместо значения
# sqlalchemy.url из alembic.ini (там оставлена пустая заглушка)
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# метаданные всех моделей — нужно для `alembic revision --autogenerate`
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
