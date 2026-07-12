"""contragents: новые таблицы + теги на templates

Revision ID: 980b30cdc402
Revises:
Create Date: 2026-07-12

Первая ревизия Alembic в проекте (до этого схема жила на create_all(),
см. app/db.py). Ничего не удаляет и не пересоздаёт существующие таблицы:

  - contragents / contragent_nicknames — новые таблицы, безопасно
  - templates.country / contragent_type / contract_family —
    ALTER TABLE ADD COLUMN, nullable — существующие 8 шаблонов не теряются,
    просто первое время у них эти три поля будут NULL, пока не дозаполнят
    вручную (см. шаг 2 плана из брейншторма).

Данные шаблонов и всё остальное содержимое БД миграция не трогает.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "980b30cdc402"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- новые колонки-теги на существующей таблице templates ---
    op.add_column("templates", sa.Column("country", sa.String(length=16), nullable=True))
    op.add_column("templates", sa.Column("contragent_type", sa.String(length=16), nullable=True))
    op.add_column("templates", sa.Column("contract_family", sa.String(length=32), nullable=True))

    # --- contragents ---
    op.create_table(
        "contragents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("country", sa.String(length=16), nullable=True),
        sa.Column("type", sa.String(length=16), nullable=True),
        sa.Column("contract_family", sa.String(length=32), nullable=True),
        sa.Column("contract_date", sa.Date(), nullable=True),
        sa.Column("contract_number", sa.String(length=64), nullable=True),
        sa.Column("royalty_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # индекс под ILIKE-поиск по title (см. брейншторм: поиск контрагента по title/nickname)
    op.create_index("ix_contragents_title", "contragents", ["title"])

    # --- contragent_nicknames ---
    op.create_table(
        "contragent_nicknames",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "contragent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contragents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nickname", sa.String(length=255), nullable=False),
    )
    op.create_index(
        "ix_contragent_nicknames_nickname", "contragent_nicknames", ["nickname"]
    )
    op.create_index(
        "ix_contragent_nicknames_contragent_id",
        "contragent_nicknames",
        ["contragent_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_contragent_nicknames_contragent_id", table_name="contragent_nicknames")
    op.drop_index("ix_contragent_nicknames_nickname", table_name="contragent_nicknames")
    op.drop_table("contragent_nicknames")

    op.drop_index("ix_contragents_title", table_name="contragents")
    op.drop_table("contragents")

    op.drop_column("templates", "contract_family")
    op.drop_column("templates", "contragent_type")
    op.drop_column("templates", "country")
