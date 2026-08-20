"""reg_number: снять UNIQUE (оставить обычный индекс)

Revision ID: b8e2d4f6a1c9
Revises: a7f3e1c9d2b4
Create Date: 2026-08-11

Рег. номер больше НЕ уникален: у одного человека бывают отдельные карточки на
аванс и роялти с одним и тем же ИНН/ОГРНИП. Уникальный идентификатор контрагента
теперь — dista_id (наш код из Dista, у него UNIQUE остаётся). Здесь пересоздаём
индекс `ix_contragents_reg_number` как НЕ уникальный (поиск по рег.номеру
сохраняем, ограничение на дубли снимаем).

Аддитивно-совместимо: колонка та же, меняется только уникальность индекса.
Код, снимающий проверки уникальности рег.номера, приезжает этим же деплоем.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "b8e2d4f6a1c9"
down_revision = "a7f3e1c9d2b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_contragents_reg_number", table_name="contragents")
    op.create_index("ix_contragents_reg_number", "contragents", ["reg_number"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_contragents_reg_number", table_name="contragents")
    op.create_index("ix_contragents_reg_number", "contragents", ["reg_number"], unique=True)
