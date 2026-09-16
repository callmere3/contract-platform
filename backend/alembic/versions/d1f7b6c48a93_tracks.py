"""номенклатура: tracks и track_rights

Revision ID: d1f7b6c48a93
Revises: c5a2f8b31e47
Create Date: 2026-09-16

Каталог лейбла из Dista: 121 529 треков и до шести строк прав на каждый.

Две таблицы, а не одна широкая. В выгрузке права разложены по нумерованным
колонкам («Владелец авт.прав 1», «Доля(%) авт.прав 1», …, и так до третьего
места), то есть таблица растёт вправо с каждым новым правообладателем и
обрывается там, где кончились заготовленные колонки. У нас право — строка:
сколько правообладателей, столько и строк, четвёртый появится без миграции.

Индексы поставлены под то, как каталог ищут: артикул (он же ключ импорта),
ISRC/UPC, название, исполнитель, каталог и владелец права. Поиск по
подстроке индексом всё равно не покроется — на 121 тысяче строк это и не
нужно, — но точное совпадение по артикулу обязано быть мгновенным: импорт
дёргает его на каждую строку файла.

Права удаляются вместе с треком (CASCADE) — они его часть, а не
самостоятельная сущность: импорт замещает состав прав целиком, сначала
снося прежние строки.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d1f7b6c48a93"
down_revision = "c5a2f8b31e47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tracks",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("sku", sa.String(32), nullable=False),
        sa.Column("code", sa.String(64)),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("artist", sa.String(300)),
        sa.Column("authors", sa.Text()),
        sa.Column("share_author", sa.Numeric(6, 2)),
        sa.Column("share_related", sa.Numeric(6, 2)),
        sa.Column("catalog", sa.String(255)),
        sa.Column("album", sa.String(300)),
        sa.Column("genre", sa.String(120)),
        sa.Column("royalty_percent", sa.Numeric(6, 2)),
        sa.Column("rights_since", sa.Date()),
        sa.Column("source_file", sa.String(160)),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_tracks_sku", "tracks", ["sku"], unique=True)
    op.create_index("ix_tracks_code", "tracks", ["code"])
    op.create_index("ix_tracks_title", "tracks", ["title"])
    op.create_index("ix_tracks_artist", "tracks", ["artist"])
    op.create_index("ix_tracks_catalog", "tracks", ["catalog"])

    op.create_table(
        "track_rights",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "track_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tracks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("right_type", sa.String(8), nullable=False),
        sa.Column("slot", sa.SmallInteger(), nullable=False),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("share", sa.Numeric(6, 2)),
        sa.Column("royalty", sa.Numeric(6, 2)),
    )
    op.create_index("ix_track_rights_track_id", "track_rights", ["track_id"])
    op.create_index("ix_track_rights_owner", "track_rights", ["owner"])


def downgrade() -> None:
    op.drop_table("track_rights")
    op.drop_table("tracks")
