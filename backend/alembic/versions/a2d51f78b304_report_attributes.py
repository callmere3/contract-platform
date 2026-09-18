"""Отчёты партнёров: параметры отчёта и неразнесённая сумма

Revision ID: a2d51f78b304
Revises: f4a6b2c98e71
Create Date: 2026-09-18

Четыре параметра — тип контента, тип и вид использования, территория (как в
Dista). Они одинаковы для всего отчёта и дальше уйдут в отчёт
правообладателю. Лежат в ДВУХ местах: у правила партнёра — значения по
умолчанию (вбивать их каждый раз заново незачем), у загруженного отчёта —
снимок на момент загрузки, ровно как ставка НДС.

`unmatched_amount` — сумма строк, которым не нашлось трека. Показываем её
вместо числа таких строк: десять строк по рублю и одна на сто тысяч выглядят
одинаково, если считать строки. Для уже загруженных отчётов считается здесь
же, из их строк.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a2d51f78b304"
down_revision = "f4a6b2c98e71"
branch_labels = None
depends_on = None

ATTRS = ("content_type", "usage_type", "usage_kind", "territory")


def upgrade() -> None:
    for table in ("partner_report_rules", "partner_reports"):
        for name in ATTRS:
            op.add_column(table, sa.Column(name, sa.String(120)))
    op.add_column(
        "partner_reports",
        sa.Column(
            "unmatched_amount", sa.Numeric(16, 4), nullable=False, server_default="0"
        ),
    )
    # Уже загруженным отчётам считаем сумму по их же строкам: число
    # неразнесённых строк у них есть, а суммы не было.
    op.execute(
        """
        UPDATE partner_reports r
           SET unmatched_amount = COALESCE((
                   SELECT sum(coalesce(w.amount_author, 0) + coalesce(w.amount_related, 0))
                     FROM partner_report_rows w
                    WHERE w.report_id = r.id AND w.track_id IS NULL
               ), 0)
        """
    )


def downgrade() -> None:
    op.drop_column("partner_reports", "unmatched_amount")
    for table in ("partner_reports", "partner_report_rules"):
        for name in ATTRS:
            op.drop_column(table, name)
