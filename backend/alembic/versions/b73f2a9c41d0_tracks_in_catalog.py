"""Номенклатура: Каталог и неКаталог

Revision ID: b73f2a9c41d0
Revises: e9c47b31d8a5
Create Date: 2026-09-18

Изъятые позиции лежат в той же таблице и отличаются одним флагом: поля у них
те же, права те же, и весь код показа, поиска и выгрузки общий. Отдельная
таблица означала бы вторую копию всего этого ради одного «где лежит».

Это НЕ `archived_at`: архив — «строка исчезла из выгрузки Dista», наблюдение;
неКаталог — решение изъять позицию, и приезжает оно отдельным файлом.

Всё, что уже залито (121 529 треков), — каталог: до сегодняшнего дня другого
списка не существовало.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b73f2a9c41d0"
down_revision = "e9c47b31d8a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tracks",
        sa.Column(
            "in_catalog", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )


def downgrade() -> None:
    op.drop_column("tracks", "in_catalog")
