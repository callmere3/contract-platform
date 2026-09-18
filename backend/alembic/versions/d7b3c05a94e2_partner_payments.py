"""ML Finance: поступления от площадок

Revision ID: d7b3c05a94e2
Revises: c81e4a2f6d59
Create Date: 2026-09-19

Отчёт площадки говорит, что она насчитала; поступление — что реально дошло до
счёта: когда, сколько, по какому курсу и сколько из этого завели. Одним
платежом закрывают несколько отчётов, а курс и завод к отчёту отношения не
имеют — поэтому таблица своя, а не колонки у отчёта.

Площадка nullable: строку заводят по выписке, а чей это платёж, иногда
выясняют потом. RESTRICT на партнёра — та же причина, что у контрагента с
операциями: удаление справочной строки не должно молча стирать деньги.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = "d7b3c05a94e2"
down_revision = "c81e4a2f6d59"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "partner_payments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column(
            "partner_id",
            UUID(as_uuid=True),
            sa.ForeignKey("partners.id", ondelete="RESTRICT"),
        ),
        sa.Column("description", sa.Text()),
        sa.Column("amount", sa.Numeric(16, 2)),
        sa.Column("rate", sa.Numeric(14, 6)),
        sa.Column("transfer_amount", sa.Numeric(16, 2)),
        sa.Column(
            "transferred", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("actual_amount", sa.Numeric(16, 2)),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_partner_payments_occurred_on", "partner_payments", ["occurred_on"])
    op.create_index("ix_partner_payments_partner_id", "partner_payments", ["partner_id"])


def downgrade() -> None:
    op.drop_index("ix_partner_payments_partner_id", table_name="partner_payments")
    op.drop_index("ix_partner_payments_occurred_on", table_name="partner_payments")
    op.drop_table("partner_payments")
