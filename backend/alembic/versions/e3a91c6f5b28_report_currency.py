"""Отчёт площадки: валюта и курс к рублю

Believe присылает отчёты в разной валюте: RU в рублях, KZ в евро, AE в
долларах (образцы владельца 24.09.2026). Суммы переводятся в рубли при
разборе по курсу, который человек вписывает в форме загрузки, а в отчёте
остаётся снимок — в какой валюте был файл и по какому курсу его перевели.

Обе колонки nullable: у рублёвых отчётов и у всех загруженных раньше их нет.

Revision ID: e3a91c6f5b28
Revises: d2b87f4c1e69
"""
import sqlalchemy as sa
from alembic import op

revision = "e3a91c6f5b28"
down_revision = "d2b87f4c1e69"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("partner_reports", sa.Column("currency", sa.String(length=32), nullable=True))
    op.add_column(
        "partner_reports", sa.Column("currency_rate", sa.Numeric(20, 10), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("partner_reports", "currency_rate")
    op.drop_column("partner_reports", "currency")
