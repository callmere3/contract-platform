"""Отчёты партнёров: запомненные сопоставления «трек → артикул»

Revision ID: c81e4a2f6d59
Revises: a2d51f78b304
Create Date: 2026-09-18

Артикул, вписанный руками в предпросмотре, запоминается для площадки: в
следующем её отчёте тот же трек приедет уже с артикулом. Ключ — площадка плюс
нормализованные название и исполнитель; артикул хранится строкой, а не ссылкой
на трек, — он наш код и переживает перезаливку каталога.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = "c81e4a2f6d59"
down_revision = "a2d51f78b304"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "partner_track_aliases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "partner_id",
            UUID(as_uuid=True),
            sa.ForeignKey("partners.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title_key", sa.String(300), nullable=False),
        sa.Column("artist_key", sa.String(300), nullable=False),
        sa.Column("title", sa.String(300)),
        sa.Column("artist", sa.String(300)),
        sa.Column("sku", sa.String(32), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("partner_id", "title_key", "artist_key", name="uq_alias_key"),
    )
    op.create_index("ix_partner_track_aliases_partner_id", "partner_track_aliases", ["partner_id"])


def downgrade() -> None:
    op.drop_index("ix_partner_track_aliases_partner_id", table_name="partner_track_aliases")
    op.drop_table("partner_track_aliases")
