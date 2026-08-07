"""contragent dista_excluded (не заводить в Dista — тестовые контрагенты)

Revision ID: a7f3e1c9d2b4
Revises: f4c2a1e9b7d3
Create Date: 2026-08-08

Признак «не заводить в Dista»: карточка без dista_id, помеченная этим флагом,
исчезает из списка «Нет в Dista» (вкладка Dista Connect) и не считается
несвязанной, требующей внимания. Нужно для тестовых контрагентов, которых
заводят под обкатку шаблонов договоров и в Dista добавлять не нужно.

NOT NULL со server_default false — существующие карточки получают false без
простоя. Аддитивная колонка; порядок деплоя обычный: push → alembic upgrade →
touch main.py (код читает колонку в запросах Dista Connect, см. CLAUDE.md).
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a7f3e1c9d2b4"
down_revision = "f4c2a1e9b7d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contragents",
        sa.Column(
            "dista_excluded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("contragents", "dista_excluded")
