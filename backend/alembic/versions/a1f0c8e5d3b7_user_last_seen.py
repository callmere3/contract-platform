"""users: колонка last_seen_at (статус в сети)

Revision ID: a1f0c8e5d3b7
Revises: 9d4b2e7a1f53
Create Date: 2026-07-16

Время последнего авторизованного запроса пользователя — по нему вкладка
"Пользователи" показывает статус "в сети" (< 5 минут) или время последнего
использования. Обновляется в get_current_user (app/auth.py) с троттлингом.
Nullable: у пользователей, ни разу не заходивших после ввода фичи, значения
ещё нет.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1f0c8e5d3b7"
down_revision = "9d4b2e7a1f53"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "last_seen_at")
