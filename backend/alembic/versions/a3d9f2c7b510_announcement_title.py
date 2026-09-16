"""announcements.title: заголовок уведомления

Revision ID: a3d9f2c7b510
Revises: e2b6d4a91c37
Create Date: 2026-09-16

В панели уведомления лежат списком, и по первым словам текста не всегда
понятно, о чём объявление. Заголовок снимает необходимость читать каждое,
чтобы это выяснить.

Колонка NULLABLE, и заполнять старые строки задним числом нечем: у
отправленных до этой даты заголовка нет и взяться ему неоткуда — придумать
за автора значило бы подписать его словами, которых он не писал. Такие
уведомления показываются как раньше, одним текстом. Новые без заголовка не
создаются, но проверка эта на уровне API (NewAnnouncement), а не схемы:
NOT NULL здесь означал бы DEFAULT '' для истории, то есть тот же пустой
заголовок, только неотличимый от заполненного.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a3d9f2c7b510"
down_revision = "e2b6d4a91c37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("announcements", sa.Column("title", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("announcements", "title")
