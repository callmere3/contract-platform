"""generated_documents: история генерации документов

Revision ID: 7c1e9a4f6b02
Revises: 3f7a1c9d2b44
Create Date: 2026-07-16

Этап 7 (брейншторм "История генерации"): отдельная таблица для вкладки
"История генерации" (Admin, Director) — кто/когда/по какому контрагенту и
шаблону сгенерировал документ. Готовый файл нигде не хранится — вместо
этого запоминаются payload формы и template_id, чтобы при необходимости
воссоздать документ (см. GeneratedDocument в app/models.py).

Ничего не удаляет и не трогает существующие таблицы.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "7c1e9a4f6b02"
down_revision = "3f7a1c9d2b44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generated_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_username", sa.String(length=255), nullable=True),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("template_name", sa.String(length=255), nullable=False),
        sa.Column(
            "contragent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contragents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("contragent_title", sa.String(length=255), nullable=True),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_generated_documents_created_at", "generated_documents", ["created_at"]
    )
    op.create_index(
        "ix_generated_documents_contragent_id", "generated_documents", ["contragent_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_generated_documents_contragent_id", table_name="generated_documents")
    op.drop_index("ix_generated_documents_created_at", table_name="generated_documents")
    op.drop_table("generated_documents")
