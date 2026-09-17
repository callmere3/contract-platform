"""Отчёты партнёров: период — пара дат, артикул необязателен

Revision ID: d4a71c9e52f8
Revises: c5e2a83d47b1
Create Date: 2026-09-18

Три правки по первым настоящим файлам площадок (отчёты МТС, 18.09.2026):

1. ПЕРИОД — ПАРА ДАТ вместо «год + квартал». МТС отчитывается за МЕСЯЦ («за
   период с 1 июля 2026 по 31 июля 2026»), кто-то за квартал, а бывает и
   произвольный отрезок. Пара дат вмещает всё; месяц и квартал в интерфейсе —
   просто кнопки, которые её заполняют.

2. АРТИКУЛ НЕОБЯЗАТЕЛЕН. В отчёте МТС два десятка строк без кода объекта:
   деньги по ним пришли, а код площадка не проставила. Такие строки грузятся
   без ссылки на трек и считаются отдельно, а не роняют файл.

3. `problem_count` — строк, где сумма не прочиталась или формула дала пустоту.
   Они грузятся с нулями: терять квартальный отчёт из-за одной строки нельзя,
   но и молчать о ней тоже.

Таблицы на момент правки пустые (вкладка появилась в тот же день), поэтому
колонки периода меняются без переноса данных.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4a71c9e52f8"
down_revision = "c5e2a83d47b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_partner_reports_period", table_name="partner_reports")
    op.drop_column("partner_reports", "period_year")
    op.drop_column("partner_reports", "period_quarter")
    op.add_column("partner_reports", sa.Column("period_from", sa.Date(), nullable=False))
    op.add_column("partner_reports", sa.Column("period_to", sa.Date(), nullable=False))
    op.add_column(
        "partner_reports",
        sa.Column("problem_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_partner_reports_period", "partner_reports", ["period_from", "period_to"]
    )
    op.alter_column("partner_report_rows", "sku", existing_type=sa.String(32), nullable=True)
    # Суммы строк — четыре знака: площадки считают дробно, и округление каждой
    # строки до копеек уводит итог отчёта от «Итого» самой площадки.
    op.alter_column("partner_report_rows", "amount_author",
                    existing_type=sa.Numeric(14, 2), type_=sa.Numeric(16, 4))
    op.alter_column("partner_report_rows", "amount_related",
                    existing_type=sa.Numeric(14, 2), type_=sa.Numeric(16, 4))


def downgrade() -> None:
    op.alter_column("partner_report_rows", "amount_author",
                    existing_type=sa.Numeric(16, 4), type_=sa.Numeric(14, 2))
    op.alter_column("partner_report_rows", "amount_related",
                    existing_type=sa.Numeric(16, 4), type_=sa.Numeric(14, 2))
    op.alter_column("partner_report_rows", "sku", existing_type=sa.String(32), nullable=False)
    op.drop_index("ix_partner_reports_period", table_name="partner_reports")
    op.drop_column("partner_reports", "problem_count")
    op.drop_column("partner_reports", "period_to")
    op.drop_column("partner_reports", "period_from")
    op.add_column("partner_reports", sa.Column("period_year", sa.SmallInteger(), nullable=False))
    op.add_column("partner_reports", sa.Column("period_quarter", sa.SmallInteger(), nullable=False))
    op.create_index(
        "ix_partner_reports_period", "partner_reports", ["period_year", "period_quarter"]
    )
