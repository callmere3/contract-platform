"""номенклатура: триграммный индекс на владельца права

Revision ID: e3b7d95c2f18
Revises: d8c3e15a90f4
Create Date: 2026-09-17

Продолжение d8c3e15a90f4. Индексы на треках ускорили общий поиск в десятки
раз (1.1 с → 0.02–0.12 с), но фильтр по правообладателю остался на 1.19 с:
он ищет подстроку в `track_rights.owner`, а это своя таблица на 243 934
строки, и btree-индекс на `owner` для `ILIKE '%…%'` так же бесполезен.

Отдельной миграцией, а не правкой предыдущей: та уже накачена на проде, и
переписывать применённую миграцию — верный способ получить расхождение между
базой и историей.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "e3b7d95c2f18"
down_revision = "d8c3e15a90f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_track_rights_owner_trgm "
        "ON track_rights USING gin (owner gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_track_rights_owner_trgm")
