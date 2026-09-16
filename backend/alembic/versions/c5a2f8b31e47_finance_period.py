"""finance_operations: период поступления (кварталы)

Revision ID: c5a2f8b31e47
Revises: b7e4c1a9d052
Create Date: 2026-09-16

Поступление — это квартальный отчёт, и он относится к кварталу, а не к дате
зачисления: деньги за I квартал приходят в апреле, а одним платежом нередко
закрывают несколько кварталов сразу. Отсюда пара (год, квартал) начала и
конца; у одного квартала они совпадают.

Четыре маленьких числа, а не строка «2026-Q1» и не даты: строку пришлось бы
разбирать везде, где нужно сравнение, а даты выглядели бы точнее, чем есть —
«с 01.01 по 31.03» человек не вводил, и первый же отчёт по кварталам начал бы
угадывать их обратно.

Колонки nullable: у расходов периода нет вовсе. Обязательность у поступлений
живёт в приложении (_parse_period), а не в схеме — NOT NULL здесь запретил бы
и расходы тоже.

Таблица заведена вчера и на момент миграции пуста, поэтому заполнять
существующие строки нечем и не нужно.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c5a2f8b31e47"
down_revision = "b7e4c1a9d052"
branch_labels = None
depends_on = None

COLUMNS = (
    "period_year_from",
    "period_quarter_from",
    "period_year_to",
    "period_quarter_to",
)


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column("finance_operations", sa.Column(name, sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    for name in COLUMNS:
        op.drop_column("finance_operations", name)
