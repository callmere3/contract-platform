"""finance_operations: поступления и расходы по контрагентам (ML Finance)

Revision ID: b7e4c1a9d052
Revises: a3d9f2c7b510
Create Date: 2026-09-16

Новая таблица, существующие не трогает — накатывается на живой базе без
простоя. Баланс контрагента отдельной колонкой НЕ хранится: он сумма этих
строк (app/finance.py). Хранимый баланс был бы вторым источником правды и
разъехался бы с операциями при первой же правке мимо приложения.

ondelete='RESTRICT' у ссылки на контрагента — намеренно, а не по забывчивости:
каскад означал бы, что удаление карточки молча стирает денежную историю.
Удаление контрагента с операциями теперь отвечает 409 с понятным текстом
(см. delete_contragent).

Индексы: по contragent_id — им берут карточку и балансы страницы списка;
по occurred_on — по нему операции сортируются и будут фильтроваться по
периоду.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "b7e4c1a9d052"
down_revision = "a3d9f2c7b510"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finance_operations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "contragent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contragents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("document_number", sa.String(length=64), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_username", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_finance_operations_contragent_id", "finance_operations", ["contragent_id"]
    )
    op.create_index("ix_finance_operations_occurred_on", "finance_operations", ["occurred_on"])


def downgrade() -> None:
    op.drop_index("ix_finance_operations_occurred_on", table_name="finance_operations")
    op.drop_index("ix_finance_operations_contragent_id", table_name="finance_operations")
    op.drop_table("finance_operations")
