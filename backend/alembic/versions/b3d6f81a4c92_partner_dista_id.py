"""партнёры: код в Dista

Revision ID: b3d6f81a4c92
Revises: a7c4e21b9f36
Create Date: 2026-09-17

Чтобы сверять справочник площадок с Dista по коду, а не по имени: имена
расходятся первыми («Яндекс Музыка» против «Yandex Music»), а код не
меняется. Та же роль и те же свойства, что у dista_id контрагента — связь
1:1 (unique) и nullable: у части партнёров кода не будет, пока не проставят.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b3d6f81a4c92"
down_revision = "a7c4e21b9f36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("partners", sa.Column("dista_id", sa.String(32), nullable=True))
    op.create_unique_constraint("uq_partners_dista_id", "partners", ["dista_id"])


def downgrade() -> None:
    op.drop_constraint("uq_partners_dista_id", "partners", type_="unique")
    op.drop_column("partners", "dista_id")
