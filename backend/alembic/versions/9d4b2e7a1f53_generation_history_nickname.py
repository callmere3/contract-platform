"""generated_documents: колонка nickname

Revision ID: 9d4b2e7a1f53
Revises: 7c1e9a4f6b02
Create Date: 2026-07-16

Псевдоним, для которого сгенерирован конкретный документ (значение поля
'nickname' из payload формы на момент генерации) — нужен для фильтрации
в "Истории генерации" и для отображения в списке. См. GeneratedDocument
в app/models.py.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "9d4b2e7a1f53"
down_revision = "7c1e9a4f6b02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generated_documents", sa.Column("nickname", sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("generated_documents", "nickname")
