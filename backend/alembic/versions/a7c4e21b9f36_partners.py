"""ML Finance: справочник партнёров

Revision ID: a7c4e21b9f36
Revises: f2a91c73d8e5
Create Date: 2026-09-17

Партнёр — площадка или агрегатор, от которого приходят деньги. Таблица
намеренно из одного значащего поля: партнёр нужен, чтобы поступление было к
кому отнести, а договор, реквизиты и ставки живут в карточках контрагентов.

Отдельная таблица, а не тип контрагента: контрагент — тот, КОМУ мы платим,
партнёр — тот, КТО платит нам; в расчёте их пути расходятся полностью.

Имя уникально: справочник, в котором «Яндекс Музыка» лежит трижды,
справочником быть перестаёт.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7c4e21b9f36"
down_revision = "f2a91c73d8e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "partners",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_partners_name", "partners", ["name"], unique=True)


def downgrade() -> None:
    op.drop_table("partners")
