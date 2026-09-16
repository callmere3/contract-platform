"""announcement_recipients.hidden_at: получатель убрал уведомление у себя

Revision ID: d4a8c1b6f720
Revises: c9f4b2e7a318
Create Date: 2026-09-16

Пользователь может удалить полученное уведомление. Удаляем НЕ строку, а
помечаем её скрытой: строка — это ещё и отметка «кому адресовано» и
«прочитал ли», на которой держится админское «прочитали 3 из 7». Удали её
физически — у админа молча уменьшился бы знаменатель, а человек исчез бы из
списка получателей, будто ему и не отправляли.

Аддитивная миграция: одна nullable-колонка, существующие данные не трогает.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d4a8c1b6f720"
down_revision = "c9f4b2e7a318"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "announcement_recipients",
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("announcement_recipients", "hidden_at")
