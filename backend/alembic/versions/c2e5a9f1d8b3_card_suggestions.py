"""card_suggestions: предложения дозаполнить карточку контрагента (вкладка "Уведомления")

Revision ID: c2e5a9f1d8b3
Revises: b3d1f7c02a9e
Create Date: 2026-07-31

Новая таблица под фичу "Уведомления" (только admin): при генерации документа
менеджер вписывает недостающие карточке данные (в первую очередь reg_number),
и они попадают сюда как pending-предложения — админ применяет их к карточке
галочкой или отклоняет крестиком. См. app/models.py: CardSuggestion и
app/suggestions.py (захват при генерации).

Аддитивная миграция: только CREATE TABLE, существующие данные не трогает —
безопасна даже при живом api. Накатывается ОТДЕЛЬНЫМ деплоем ДО кода, который
таблицу читает/пишет, чтобы не поймать окно "код ↔ схема" (см. CLAUDE.md).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "c2e5a9f1d8b3"
down_revision = "b3d1f7c02a9e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_suggestions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "contragent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contragents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("field", sa.String(32), nullable=False),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column(
            "suggested_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("suggested_by_username", sa.String(255), nullable=True),
        sa.Column(
            "source_generation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("generated_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "resolved_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("card_suggestions")
