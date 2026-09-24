"""Отчёт площадки: итог в исходной валюте

Сверка валютного отчёта с платежом идёт В ВАЛЮТЕ: итог отчёта сравнивается
с «суммой в валюте» поступления, и только если сошлось, курс к рублю
ставится сам (просьба владельца 24.09.2026). Курс, выведенный из того же
платежа без такой сверки, делал бы её замкнутой — неполный отчёт «сходился»
бы всегда. Для сверки нужен итог в исходной валюте, отсюда колонка.

Nullable: у рублёвых отчётов и у загруженных раньше его нет.

Revision ID: f1c5a9d27e43
Revises: e3a91c6f5b28
"""
import sqlalchemy as sa
from alembic import op

revision = "f1c5a9d27e43"
down_revision = "e3a91c6f5b28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "partner_reports", sa.Column("currency_total", sa.Numeric(20, 8), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("partner_reports", "currency_total")
