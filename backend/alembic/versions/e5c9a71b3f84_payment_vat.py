"""Поступления: столбец НДС

Revision ID: e5c9a71b3f84
Revises: d7b3c05a94e2
Create Date: 2026-09-19

НДС хранится СУММОЙ, а не ставкой: в поступлениях сверяют деньги, и «сколько
из них налог» отвечает на вопрос прямо. Ставка и так известна, а от площадки
нередко приходит уже посчитанная сумма.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e5c9a71b3f84"
down_revision = "d7b3c05a94e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("partner_payments", sa.Column("vat_amount", sa.Numeric(16, 2)))


def downgrade() -> None:
    op.drop_column("partner_payments", "vat_amount")
