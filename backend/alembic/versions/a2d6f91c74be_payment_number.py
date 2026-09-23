"""Номер поступления берётся из файла, а не вычисляется

Нумерация в таблице должна совпадать с первым столбцом выписки: им называют
строку вслух и на него ссылается вкладка «Отчёты». Вычисленный «порядок
заведения» для этого не годился — весь файл заводится одним импортом, и у
всех строк одинаковый `created_at`, так что порядок внутри месяца оставался
на усмотрение сортировки по id.

Колонка nullable: у строк, заведённых до этой правки, номера из файла нет —
они получают свободные номера вслед за занятыми (см. `payment_numbers`).

Revision ID: a2d6f91c74be
Revises: f7c284b06e91
"""
import sqlalchemy as sa
from alembic import op

revision = "a2d6f91c74be"
down_revision = "f7c284b06e91"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("partner_payments", sa.Column("number", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("partner_payments", "number")
