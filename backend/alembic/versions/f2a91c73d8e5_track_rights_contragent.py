"""номенклатура: право ссылается на карточку контрагента

Revision ID: f2a91c73d8e5
Revises: e3b7d95c2f18
Create Date: 2026-09-17

До этой миграции правообладатель в каталоге был просто строкой. Совпадало
это с базой контрагентов почти идеально — 242 673 строки прав из 243 986
сходились с титлом карточки буква в букву, — но «почти» здесь дорого стоит:
переименование карточки рвало связь молча, а у одного лейбла в каталоге
встречалось два написания («ООО Густ Мьюзик» и «ООО ГУСТ МЬЮЗИК», 26 609 и
1 132 трека), и по строковому совпадению часть треков просто не находилась.

Считать по таким совпадениям выплаты нельзя, поэтому у права появляется
настоящая ссылка. Имя из выгрузки при этом остаётся в `owner`: по нему
сверяют файл глазами, и подменять его титлом карточки — значит терять
источник.

Колонка NULLABLE: строка может прийти с именем, которого в базе ещё нет.
Заполняется двумя путями — импортом (он же заводит недостающие карточки) и
разовым скриптом `ops/link_track_rights.py` для уже залитых 244 тысяч строк.

ondelete RESTRICT, а не SET NULL: карточка, на которую ссылается каталог, не
должна удаляться молча — иначе треки остались бы без правообладателя, и
узнали бы мы об этом на первом же расчёте. Ровно та же защита, что у
контрагента с финансовыми операциями.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f2a91c73d8e5"
down_revision = "e3b7d95c2f18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "track_rights",
        sa.Column("contragent_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_track_rights_contragent",
        "track_rights",
        "contragents",
        ["contragent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_track_rights_contragent_id", "track_rights", ["contragent_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_track_rights_contragent_id", table_name="track_rights")
    op.drop_constraint("fk_track_rights_contragent", "track_rights", type_="foreignkey")
    op.drop_column("track_rights", "contragent_id")
