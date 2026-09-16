"""user_events: следы действий в интерфейсе, которых нет в других таблицах

Revision ID: e2b6d4a91c37
Revises: d4a8c1b6f720
Create Date: 2026-09-16

Нужна достижению «Разбитое сердце» — выйти из формы генерации, не сохранив
черновик. Такое действие не оставляет следа нигде: документ не создан,
черновик стёрт, в журнал действий это не пишется (журнал про работу с
данными, а не про клики). Считать его не из чего, поэтому — отдельная
строчка-событие.

Таблица НАРОЧНО общая, а не «черновики»: событий такого рода будет больше
(открыл инструкцию, отменил что-то), и заводить таблицу под каждое —
расточительно. Имя события хранится строкой, но принимается сервером
только из белого списка (см. routers_profile.py): иначе любой клиент мог
бы насыпать сюда произвольного мусора.

Аддитивная миграция: только CREATE TABLE, существующие данные не трогает.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "e2b6d4a91c37"
down_revision = "d4a8c1b6f720"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        # CASCADE: события живут ровно столько, сколько учётка. Это не
        # журнал аудита, восстанавливать их по удалённому пользователю незачем.
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # Достижения спрашивают «было ли у этого человека такое событие» —
    # индекс ровно под этот вопрос.
    op.create_index("ix_user_events_user_event", "user_events", ["user_id", "event"])


def downgrade() -> None:
    op.drop_index("ix_user_events_user_event", table_name="user_events")
    op.drop_table("user_events")
