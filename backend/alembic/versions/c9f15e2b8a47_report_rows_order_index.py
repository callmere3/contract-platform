"""Строки отчёта — индекс (отчёт, номер строки)

Окно загруженного отчёта показывает его ОДНОЙ таблицей со сплошной
прокруткой (просьба владельца 24.09.2026), а строки подгружает кусками по
мере прокрутки: `ORDER BY row_num OFFSET … LIMIT 500` в пределах отчёта.
С индексом только по report_id каждый такой кусок сортировал бы весь отчёт
заново — у Believe это полмиллиона строк на каждый шаг прокрутки. Составной
индекс отдаёт их уже по порядку.

Прежний индекс по одному report_id убран: составной начинается с той же
колонки и обслуживает те же запросы, а лишний индекс — это лишняя работа
при каждой загрузке отчёта через COPY.

Revision ID: c9f15e2b8a47
Revises: b8e3f04a7c12
"""
from alembic import op

revision = "c9f15e2b8a47"
down_revision = "b8e3f04a7c12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_partner_report_rows_report_row",
        "partner_report_rows",
        ["report_id", "row_num"],
    )
    op.drop_index("ix_partner_report_rows_report_id", table_name="partner_report_rows")


def downgrade() -> None:
    op.create_index(
        "ix_partner_report_rows_report_id", "partner_report_rows", ["report_id"]
    )
    op.drop_index("ix_partner_report_rows_report_row", table_name="partner_report_rows")
