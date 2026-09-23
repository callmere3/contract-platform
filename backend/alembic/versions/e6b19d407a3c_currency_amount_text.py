"""Сумма в валюте — ТЕКСТОМ, вместе с названием валюты

Сутки поле было числом плюс отдельный код валюты. Владелец уточнил
(23.09.2026): вставлять он будет «как есть» — «8 247,81 доллар», — и разбирать
это на число и валюту незачем. Поле справочное, в расчётах не участвует, и
единственное, что от него требуется, — читаться так же, как в письме площадки.

Уже занесённые значения переносятся: «8247,81 USD». Их немного, и поле теперь
текстовое — поправить руками можно прямо в таблице.

Revision ID: e6b19d407a3c
Revises: d8e41a5c93b7
"""
import sqlalchemy as sa
from alembic import op

revision = "e6b19d407a3c"
down_revision = "d8e41a5c93b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "partner_payments",
        sa.Column("currency_text", sa.String(length=64), nullable=True),
    )
    # Число и код валюты склеиваем в ту же строку, какой её видел человек.
    op.execute(
        """
        UPDATE partner_payments
           SET currency_text =
               replace(to_char(currency_amount, 'FM9999999990.00'), '.', ',')
               || coalesce(' ' || currency, '')
         WHERE currency_amount IS NOT NULL
        """
    )
    op.drop_column("partner_payments", "currency_amount")
    op.drop_column("partner_payments", "currency")
    op.alter_column("partner_payments", "currency_text", new_column_name="currency_amount")


def downgrade() -> None:
    # Обратно разбирать текст на число и валюту не станем: гадать, где в
    # «8 247,81 доллар» число, а где валюта, — ровно то, от чего ушли.
    op.alter_column("partner_payments", "currency_amount", new_column_name="currency_text")
    op.add_column(
        "partner_payments", sa.Column("currency_amount", sa.Numeric(16, 2), nullable=True)
    )
    op.add_column(
        "partner_payments", sa.Column("currency", sa.String(length=16), nullable=True)
    )
    op.drop_column("partner_payments", "currency_text")
