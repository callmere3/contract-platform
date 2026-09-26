"""Архив Dista: история прав по датам, история начислений, отчёты задним числом

Решения владельца 26.09.2026 после разбора базы Dista (MEDIALAND.FDB):

1. `track_right_history` — ПРЕЖНИЕ составы прав трека. Текущий состав
   по-прежнему в `track_rights` (весь существующий код его и читает), а
   сюда уходит то, что действовало раньше, со сроком [valid_from, valid_to).
   Расчёт берёт для отчёта состав на КОНЕЦ ЕГО ПЕРИОДА — так считала Dista
   (проверено по её начислениям).

2. `royalty_accruals` — начисления правообладателям по периодам (у Dista —
   «Акт приёмки-сдачи работ» плюс «собрано прав» и «удержание Лицензиата»).
   Только ИСТОРИЯ: в балансы и ведомости не идёт (владелец: балансы заведём
   руками с учётом выплат, история нужна роялти-кабинетам).

3. `partner_reports.source` / `dista_doc_id` — отчёт, перенесённый из архива
   Dista, а не загруженный файлом. `dista_doc_id` уникален: повторный прогон
   переноса ничего не задваивает.

Revision ID: b4e8d1a6c2f7
Revises: a7d3e2c91f60
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "b4e8d1a6c2f7"
down_revision = "a7d3e2c91f60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "track_right_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("track_id", UUID(as_uuid=True),
                  sa.ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("valid_from", sa.Date, nullable=False),
        sa.Column("valid_to", sa.Date, nullable=False),
        sa.Column("right_type", sa.String(8), nullable=False),
        sa.Column("slot", sa.SmallInteger, nullable=False),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("contragent_id", UUID(as_uuid=True),
                  sa.ForeignKey("contragents.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("share", sa.Numeric(6, 2)),
        sa.Column("royalty", sa.Numeric(6, 2)),
        sa.Column("source", sa.String(16)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_track_right_history_track", "track_right_history",
                    ["track_id", "valid_from"])
    op.create_index("ix_track_right_history_contragent", "track_right_history",
                    ["contragent_id"])

    op.create_table(
        "royalty_accruals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("contragent_id", UUID(as_uuid=True),
                  sa.ForeignKey("contragents.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("holder_name", sa.String(255), nullable=False),
        sa.Column("period_from", sa.Date, nullable=False),
        sa.Column("period_to", sa.Date, nullable=False),
        sa.Column("accrued_on", sa.Date, nullable=False),
        sa.Column("royalty", sa.Numeric(20, 8), nullable=False),
        sa.Column("realization", sa.Numeric(20, 8)),
        sa.Column("commission", sa.Numeric(20, 8)),
        sa.Column("note", sa.Text),
        sa.Column("source", sa.String(16), nullable=False, server_default="dista"),
        sa.Column("dista_doc_id", sa.Integer, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_royalty_accruals_contragent", "royalty_accruals",
                    ["contragent_id", "period_to"])

    op.add_column("partner_reports", sa.Column("source", sa.String(16)))
    op.add_column("partner_reports", sa.Column("dista_doc_id", sa.Integer))
    op.create_unique_constraint("uq_partner_reports_dista_doc", "partner_reports",
                                ["dista_doc_id"])


def downgrade() -> None:
    op.drop_constraint("uq_partner_reports_dista_doc", "partner_reports")
    op.drop_column("partner_reports", "dista_doc_id")
    op.drop_column("partner_reports", "source")
    op.drop_index("ix_royalty_accruals_contragent", "royalty_accruals")
    op.drop_table("royalty_accruals")
    op.drop_index("ix_track_right_history_contragent", "track_right_history")
    op.drop_index("ix_track_right_history_track", "track_right_history")
    op.drop_table("track_right_history")
