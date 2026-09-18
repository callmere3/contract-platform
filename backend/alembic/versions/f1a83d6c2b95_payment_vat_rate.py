"""Поступления: НДС ставкой, а не суммой

Revision ID: f1a83d6c2b95
Revises: e5c9a71b3f84
Create Date: 2026-09-19

Уточнение владельца: в этой таблице НДС стоит рядом с курсом и работает так
же — это множитель, а не деньги. Колонка заводилась суммой днём раньше и
данных набрать не успела, поэтому просто меняем её на ставку того же типа,
что и курс.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f1a83d6c2b95"
down_revision = "e5c9a71b3f84"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("partner_payments", "vat_amount")
    op.add_column("partner_payments", sa.Column("vat_rate", sa.Numeric(14, 6)))


def downgrade() -> None:
    op.drop_column("partner_payments", "vat_rate")
    op.add_column("partner_payments", sa.Column("vat_amount", sa.Numeric(16, 2)))
