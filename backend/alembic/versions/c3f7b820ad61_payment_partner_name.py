"""partner_payments.partner_name — площадка, которой нет в справочнике

Мелкие партнёры по синхронизации отчётов не присылают, отдельными строками их
не заводят, и в справочнике площадок их нет — а деньги от них приходят и в
таблице поступлений должны быть подписаны (просьба владельца 23.09.2026).

Отдельная колонка, а не автозаведение партнёра: справочник площадок — это те,
по кому мы разбираем отчёты, и засорять его теми, кого там быть не должно,
значит сломать и выбор площадки при загрузке отчёта, и сверку при привязке.

Revision ID: c3f7b820ad61
Revises: b46d9e13c7a0
"""
import sqlalchemy as sa
from alembic import op

revision = "c3f7b820ad61"
down_revision = "b46d9e13c7a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "partner_payments",
        sa.Column("partner_name", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("partner_payments", "partner_name")
