"""contragents: reg_number — единый уникальный рег. номер (ИНН/ОГРНИП/ОГРН)

Revision ID: 3f7a1c9d2b44
Revises: f5990a238059
Create Date: 2026-07-15

Добавляет contragents.reg_number — одна колонка на ИНН (СГ), ОГРНИП (ИП) и
ОГРН (ООО) сразу: смысл значения определяется contragents.type, отдельных
колонок под каждый тип сознательно нет (см. брейншторм — "не должны быть
для базы данных разными полями").

Nullable — у уже существующих контрагентов (заведённых импортом до этой
миграции) поле пока пустое, дозаполняется вручную. Unique — теперь это
точный идентификатор контрагента для защиты от дублей (см. models.py,
докстринг Contragent — раньше "без ИНН/ОГРН точного идентификатора всё
равно нет", теперь есть). Postgres допускает сколько угодно NULL в
уникальном индексе, так что "неполные" контрагенты без reg_number друг
другу не мешают.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "3f7a1c9d2b44"
down_revision = "f5990a238059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contragents", sa.Column("reg_number", sa.String(length=15), nullable=True)
    )
    op.create_index(
        "ix_contragents_reg_number", "contragents", ["reg_number"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_contragents_reg_number", table_name="contragents")
    op.drop_column("contragents", "reg_number")
