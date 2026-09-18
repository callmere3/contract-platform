"""Отчёты партнёров: связка с поступлением

Revision ID: b46d9e13c7a0
Revises: f1a83d6c2b95
Create Date: 2026-09-19

Ссылка живёт у ОТЧЁТА, а не у платежа: одним платежом закрывают несколько
отчётов, и обратная связь потребовала бы третьей таблицы ради того же самого.
SET NULL при удалении платежа — отчёт документ площадки и живёт сам по себе, а
строку поступления могут завести заново.

«Сумма фактического завода» платежа после привязки считается как сумма
привязанных к нему отчётов: числа уже есть в базе, и переписывать их руками
значит однажды ошибиться в третьем знаке.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = "b46d9e13c7a0"
down_revision = "f1a83d6c2b95"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "partner_reports",
        sa.Column(
            "payment_id",
            UUID(as_uuid=True),
            sa.ForeignKey("partner_payments.id", ondelete="SET NULL"),
        ),
    )
    op.create_index("ix_partner_reports_payment_id", "partner_reports", ["payment_id"])


def downgrade() -> None:
    op.drop_index("ix_partner_reports_payment_id", table_name="partner_reports")
    op.drop_column("partner_reports", "payment_id")
