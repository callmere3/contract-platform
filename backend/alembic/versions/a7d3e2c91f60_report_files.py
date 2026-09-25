"""Отчёт площадки из нескольких файлов: список файлов с диапазонами строк

ВОИС присылает за месяц два файла (по договору изготовителя и по договору
исполнителя), а платит одним поступлением — владелец попросил собирать их в
ОДИН загруженный отчёт (25.09.2026). Строки файлов нумеруются сквозь, а в
`files` лежит, какой файл какие номера занял: [{name, first_row, last_row}]
— по нему окно отчёта показывает, из какого файла строка.

Nullable: у отчётов из одного файла (и у всех загруженных раньше) списка нет,
имя файла — как и было, в `file_name`.

Revision ID: a7d3e2c91f60
Revises: f1c5a9d27e43
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "a7d3e2c91f60"
down_revision = "f1c5a9d27e43"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("partner_reports", sa.Column("files", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("partner_reports", "files")
