"""partner_payments: сумма в валюте — для справки

У части площадок (CHOIS, TikTok, Believe, Spotify, Аманат) платёж приходит в
валюте, а на счёт падает уже в рублях. Валютная сумма в расчётах НЕ участвует
(просьба владельца 23.09.2026) — она нужна, чтобы сверить строку с письмом
площадки, где указана именно она.

Валюта отдельным полем, потому что в файле поступлений она написана словом
(«доллар») рядом с суммой: без неё число «8247.81» ничего не говорит.

Revision ID: d8e41a5c93b7
Revises: c3f7b820ad61
"""
import sqlalchemy as sa
from alembic import op

revision = "d8e41a5c93b7"
down_revision = "c3f7b820ad61"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "partner_payments",
        sa.Column("currency_amount", sa.Numeric(16, 2), nullable=True),
    )
    op.add_column(
        "partner_payments",
        sa.Column("currency", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("partner_payments", "currency")
    op.drop_column("partner_payments", "currency_amount")
