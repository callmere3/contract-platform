"""«Заведено» — не галочка, а выбор: да / синхра

Галочка отвечала на вопрос «завели или нет», но в рабочей таблице владельца
там третье значение — «синхра» (синхронизация). Двумя состояниями это не
описывается: пусто, «да» и «синхра» — три разных положения дел, и превращать
«синхру» в «не заведено» значит терять то, ради чего колонку и ведут.

Прежние галочки переносятся в «да». Незаведённые остаются пустыми — пусто и
значит «ещё не заведено».

Revision ID: f7c284b06e91
Revises: e6b19d407a3c
"""
import sqlalchemy as sa
from alembic import op

revision = "f7c284b06e91"
down_revision = "e6b19d407a3c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "partner_payments",
        sa.Column("transfer_status", sa.String(length=16), nullable=True),
    )
    op.execute("UPDATE partner_payments SET transfer_status = 'да' WHERE transferred")
    op.drop_column("partner_payments", "transferred")


def downgrade() -> None:
    op.add_column(
        "partner_payments",
        sa.Column("transferred", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # «Синхра» при откате станет «заведено»: в булевом поле её не выразить, а
    # потерять отметку хуже, чем огрубить её.
    op.execute("UPDATE partner_payments SET transferred = true WHERE transfer_status IS NOT NULL")
    op.drop_column("partner_payments", "transfer_status")
