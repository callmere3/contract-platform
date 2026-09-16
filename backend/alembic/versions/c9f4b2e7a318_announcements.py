"""announcements: уведомления от админа команде (вкладка "Уведомления")

Revision ID: c9f4b2e7a318
Revises: b8e2d4f6a1c9
Create Date: 2026-09-16

Вкладка "Уведомления" переделана полностью: вместо предложений дозаполнить
карточку контрагента (card_suggestions) там теперь то, что админ пишет
команде, а у каждого пользователя в шапке появляется значок с непрочитанными.

Две таблицы:
  announcements            — сам текст, кто и когда написал;
  announcement_recipients  — кому адресовано и прочитано ли (строка на
                             человека, поэтому «прочитали 3 из 7» — просто
                             COUNT, а не догадка).

Адресаты фиксируются НА МОМЕНТ ОТПРАВКИ, отдельными строками, а не флагом
«всем»: сотрудник, заведённый завтра, не должен увидеть вчерашнее
объявление, а список получателей не должен меняться задним числом, если
кого-то отключили.

СТАРУЮ ТАБЛИЦУ card_suggestions НЕ ТРОГАЕМ. Код, который в неё писал,
удалён, но данные остаются на месте: удалять таблицу с историей ради смены
экрана — несоразмерно, а вернуть логику при желании можно из git.

Аддитивная миграция: только CREATE TABLE, существующие данные не трогает.
Накатывать сразу после пуша — новый код читает эти таблицы на каждом опросе
счётчика, и до накатки они будут отвечать ошибкой (см. CLAUDE.md, окно
«код ↔ миграция»).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "c9f4b2e7a318"
down_revision = "b8e2d4f6a1c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        # SET NULL как везде: автора могут деактивировать или удалить, а
        # объявление обязано остаться читаемым — для этого рядом снимок логина.
        sa.Column(
            "author_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("author_username", sa.String(255), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_announcements_created_at", "announcements", ["created_at"])

    op.create_table(
        "announcement_recipients",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "announcement_id",
            UUID(as_uuid=True),
            sa.ForeignKey("announcements.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # CASCADE: удалили учётку — её адресные строки не нужны никому.
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        # Одно объявление — одна строка на человека: защита от повторной
        # рассылки того же самого и опора для COUNT прочитавших.
        sa.UniqueConstraint("announcement_id", "user_id", name="uq_announcement_recipient"),
    )


def downgrade() -> None:
    op.drop_table("announcement_recipients")
    op.drop_index("ix_announcements_created_at", table_name="announcements")
    op.drop_table("announcements")
