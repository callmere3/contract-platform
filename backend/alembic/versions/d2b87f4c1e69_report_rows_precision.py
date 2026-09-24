"""Суммы строк отчёта — восемь знаков после запятой вместо четырёх

Отчёт «Зайцев.нет» (образец владельца 24.09.2026): цена прослушивания там
0,024000092 ₽, и хвост 0,000000092 при округлении каждой строки до четырёх
знаков отбрасывается всегда в одну сторону. На 26 тысячах строк и 2,6 млн
прослушиваний итог отчёта уходил от «Итого» самой площадки на 11 копеек
(7 909,08 против 7 909,11 и 39 545,47 против 39 545,55).

Правило прежнее — ОКРУГЛЯЕМ ОДИН РАЗ, НА ИТОГАХ, — просто четырёх знаков для
строки оказалось мало. Восьми хватает с запасом: потеря на строку не больше
0,000000005 ₽, на полутора миллионах строк — меньше копейки.

Расширение типа данные не трогает: уже загруженные строки остаются с теми
четырьмя знаками, с какими легли. Точнее станут отчёты, загруженные заново.

Revision ID: d2b87f4c1e69
Revises: c9f15e2b8a47
"""
import sqlalchemy as sa
from alembic import op

revision = "d2b87f4c1e69"
down_revision = "c9f15e2b8a47"
branch_labels = None
depends_on = None

COLUMNS = ("amount_author", "amount_related")


def upgrade() -> None:
    for name in COLUMNS:
        op.alter_column(
            "partner_report_rows",
            name,
            type_=sa.Numeric(20, 8),
            existing_type=sa.Numeric(16, 4),
            existing_nullable=False,
        )


def downgrade() -> None:
    for name in COLUMNS:
        op.alter_column(
            "partner_report_rows",
            name,
            type_=sa.Numeric(16, 4),
            existing_type=sa.Numeric(20, 8),
            existing_nullable=False,
        )
